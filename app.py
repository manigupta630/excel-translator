import os
import uuid
import boto3
import pandas as pd
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, render_template, Response, session, redirect, url_for
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from deep_translator import GoogleTranslator
from flask_cors import CORS
from dotenv import load_dotenv
from botocore.config import Config
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from apscheduler.schedulers.background import BackgroundScheduler
from functools import wraps
from threading import Thread
from flask_pymongo import PyMongo
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from flask import session, jsonify
from bson import ObjectId

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Load environment variables from the .env file
load_dotenv()

# App configuration

app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')  # Required for sessions


# Retrieve MONGODB_URI from environment variables
MONGODB_URI = os.getenv('MONGODB_URI')
if not MONGODB_URI:
    raise ValueError("No MONGODB_URI found in environment variables")

print("Connecting to MongoDB...")

try:
    # Create a new client and connect to the server with SSL disabled (if necessary)
    client = MongoClient(MONGODB_URI, server_api=ServerApi('1'), tlsAllowInvalidCertificates=True)

    # Test the connection by sending a ping
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")

    # Simulate Flask-PyMongo's `mongo` object for backward compatibility
    class MongoWrapper:
        def __init__(self, client):
            self.cx = client  # Store the MongoClient instance
            self.db = client.get_database()  # Get the default database

        def __getattr__(self, name):
            return self.db[name]  # Dynamically access collections like `mongo.db.users`

    # Wrap the MongoClient instance to mimic Flask-PyMongo's `mongo` interface
    mongo = MongoWrapper(client)

    # Example usage of `mongo.db.users`
    users = mongo.users  # Access the 'users' collection
    existing_user = users.find_one({'email': 'example@example.com'})  # Example query
    if existing_user:
        print("User already exists:", existing_user)
    else:
        print("User does not exist.")

except Exception as e:
    print(f"Failed to connect to MongoDB: {str(e)}")
    raise

# Print the URI for debugging purposes (optional)
print(os.getenv('MONGODB_URI'))

# S3 Configuration
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.getenv('AWS_DEFAULT_REGION')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME')

s3_config = Config(signature_version='s3v4')
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
    config=s3_config
)

# Email Configuration
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USERNAME = os.getenv('EMAIL_USERNAME')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_FROM = os.getenv('EMAIL_FROM')

# App configuration
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xlsx'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/me')
@login_required  # Make sure the user is logged in before accessing this route
def me():
    user_id = session.get('user_id')
    if user_id:
        users = mongo.db.users
        user = users.find_one({'_id': ObjectId(user_id)})
        if user:
            return jsonify({'email': user['email']})
    return jsonify({'error': 'User not found'}), 404

# You can add this temporary code to test the connection
@app.route('/test_db')
def test_db():
    try:
        # Attempt to list all collections
        collections = mongo.db.list_collection_names()
        return jsonify({"status": "connected", "collections": collections})
    except Exception as e:
        return jsonify({"status": "error mani", "message": str(e)})

# Authentication routes
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        users = mongo.db.users
        
        # Check if user already exists
        existing_user = users.find_one({'email': request.form['email']})
        if existing_user:
            return jsonify({"error": "Email already exists"}), 400
        
        # Hash the password
        hashed_password = generate_password_hash(request.form['password'])
        
        # Create new user
        user_id = users.insert_one({
            'email': request.form['email'],
            'password': hashed_password,
            'created_at': datetime.utcnow()
        }).inserted_id
        
        # Start session
        session['user_id'] = str(user_id)
        return redirect(url_for('index'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        users = mongo.db.users
        
        # Find user
        user = users.find_one({'email': request.form['email']})
        
        if user and check_password_hash(user['password'], request.form['password']):
            session['user_id'] = str(user['_id'])
            return redirect(url_for('index'))
        
        return jsonify({"error": "Invalid credentials"}), 401
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Helper Functions (your existing helper functions remain the same)
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def send_email_with_attachment(recipient_email, file_path, filename):
    try:
        print(recipient_email, file_path, filename)
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = recipient_email
        msg['Subject'] = 'Your Translated Excel File'

        body = "Hello,\n\nYour Excel file has been successfully translated and attached here.\n\nBest regards,\nTranslation Service"
        msg.attach(MIMEText(body, 'plain'))

        with open(file_path, 'rb') as file:
            part = MIMEApplication(file.read(), Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            msg.attach(part)

        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.send_message(msg)

        return True
    except Exception as e:
        print(f"Email sending failed: {e}")
        return False

def upload_to_s3(file_path, bucket, object_name=None):
    if object_name is None:
        object_name = os.path.basename(file_path)
    try:
        s3_client.upload_file(
            file_path, bucket, object_name,
            ExtraArgs={'Metadata': {'upload_timestamp': str(datetime.now().timestamp())}}
        )
        return object_name
    except Exception as e:
        print(f"S3 upload failed: {e}")
        return None

def delete_old_files(folder, age_in_hours=1):
    now = datetime.now()
    cutoff_time = now - timedelta(hours=age_in_hours)

    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)
        if os.path.isfile(file_path):
            file_creation_time = datetime.fromtimestamp(os.path.getctime(file_path))
            if file_creation_time < cutoff_time:
                try:
                    os.remove(file_path)
                    print(f"Deleted old file: {file_path}")
                except Exception as e:
                    print(f"Error deleting file {file_path}: {e}")

def delete_old_s3_files(bucket):
    try:
        response = s3_client.list_objects_v2(Bucket=bucket)
        if 'Contents' in response:
            for obj in response['Contents']:
                try:
                    metadata = s3_client.head_object(Bucket=bucket, Key=obj['Key'])['Metadata']
                    upload_time = datetime.fromtimestamp(float(metadata.get('upload_timestamp', 0)))
                    if (datetime.now() - upload_time) > timedelta(hours=24):
                        s3_client.delete_object(Bucket=bucket, Key=obj['Key'])
                except Exception as e:
                    print(f"Error processing {obj['Key']}: {e}")
    except Exception as e:
        print(f"Error cleaning S3 bucket: {e}")

# Protected Routes
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part in the request"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No file selected"}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Extract Excel info
        df = pd.read_excel(filepath)
        return jsonify({
            "status": "success",
            "message": "File uploaded successfully.",
            "file_info": {
                "total_rows": df.shape[0],
                "total_columns": df.shape[1],
                "column_names": list(df.columns)
            },
            "file_path": filepath
        }), 200

    return jsonify({"status": "error", "message": "Invalid file type."}), 400

@app.route('/translate_progress', methods=['POST'])
@login_required
def translate_progress():
    file_path = request.json.get("file_path")
    source_lang = request.json.get("source_lang", "auto")
    target_lang = request.json.get("target_lang", "de")
    recipient_email = request.json.get("email")

    if not file_path or not os.path.exists(file_path):
        return jsonify({"status": "error", "message": "Invalid or missing file path."}), 400

    def generate_translation_progress():
        try:
            df = pd.read_excel(file_path)
            source_col = df.columns[1]
            target_col = df.columns[2]
            translated_text = []

            chunk_size = 120
            total_rows = len(df)

            for chunk_start in range(0, total_rows, chunk_size):
                chunk_end = min(chunk_start + chunk_size, total_rows)
                chunk = df.iloc[chunk_start:chunk_end]

                for idx, row in chunk.iterrows():
                    text = row[source_col]
                    try:
                        if pd.isna(text):
                            translated_text.append("")
                        elif isinstance(text, (int, float)) or (isinstance(text, str) and text.isnumeric()):
                            translated_text.append(text)
                        else:
                            translated = GoogleTranslator(source=source_lang, target=target_lang).translate(str(text))
                            translated_text.append(translated)
                    except Exception as e:
                        print(f"Translation error for '{text}': {e}")
                        translated_text.append("Error")
                    progress = min(int(((chunk_start + idx + 1) / total_rows) * 100), 100)
                    yield f"data: {progress}\n\n"

                time.sleep(0.1)

            df[target_col] = translated_text
            output_filename = f"translated_{uuid.uuid4().hex}.xlsx"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            df.to_excel(output_path, index=False)

            s3_object_name = upload_to_s3(output_path, S3_BUCKET_NAME)
            if s3_object_name:
                pre_signed_url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': S3_BUCKET_NAME, 'Key': s3_object_name},
                    ExpiresIn=24 * 3600
                )
                yield f"data mani: 100\n\n"
                yield f"data: complete|{pre_signed_url}\n\n"
                 
                if recipient_email:
                    def send_email():
                        email_sent = send_email_with_attachment(recipient_email, output_path, output_filename)
                        if not email_sent:
                            print("Error: Failed to send email.")

                    Thread(target=send_email).start()
            else:
                yield f"data: error|Failed to upload file to S3\n\n"
        except Exception as e:
            print(f"Error in translation progress: {e}")
            yield f"data: error|{str(e)}\n\n"

    return Response(generate_translation_progress(), content_type="text/event-stream")

@app.route('/download/<filename>', methods=['GET'])
@login_required
def download_file(filename):
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename, as_attachment=True)

# Schedule periodic cleanup tasks
scheduler = BackgroundScheduler()
scheduler.add_job(func=delete_old_files, trigger="interval", hours=1, args=[UPLOAD_FOLDER, 1])
scheduler.add_job(func=delete_old_s3_files, trigger="interval", hours=24, args=[S3_BUCKET_NAME])
scheduler.start()



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
