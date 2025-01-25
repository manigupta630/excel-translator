import os
import uuid
import boto3
import pandas as pd
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, render_template, Response
from werkzeug.utils import secure_filename
from deep_translator import GoogleTranslator
from flask_cors import CORS
from dotenv import load_dotenv
from botocore.config import Config
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from apscheduler.schedulers.background import BackgroundScheduler

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Load environment variables from the .env file
load_dotenv()

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


# Helper Functions
def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def send_email_with_attachment(recipient_email, file_path, filename):
    """Send an email with the translated file as an attachment."""
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
    """Upload file to S3."""
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
    """Delete files older than `age_in_hours` from the given folder."""
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
    """Delete files older than 24 hours from S3."""
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


# Flask Routes
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file uploads."""
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
def translate_progress():
    """Translate an uploaded Excel file and provide progress."""
    file_path = request.json.get("file_path")
    target_lang = request.json.get("target_lang", "de")
    recipient_email = request.json.get("email")  # Optional email

    if not file_path or not os.path.exists(file_path):
        return jsonify({"status": "error", "message": "Invalid or missing file path."}), 400

    def generate_translation_progress():
        try:
            df = pd.read_excel(file_path)
            source_col = df.columns[0]  # Default to the first column
            target_col = f'Translated to {target_lang}'
            translated_text = []

            for idx, text in enumerate(df[source_col], start=1):
                try:
                    translated = GoogleTranslator(source="auto", target=target_lang).translate(str(text)) if pd.notna(text) else ""
                    translated_text.append(translated)
                except Exception as e:
                    print(f"Translation error: {e}")
                    translated_text.append("Error")

                # Progress update
                yield f"data: {int((idx / len(df)) * 100)}\n\n"

            # Save translated file
            output_filename = f"translated_{uuid.uuid4().hex}.xlsx"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            df[target_col] = translated_text
            df.to_excel(output_path, index=False)

            # Upload to S3
            s3_object_name = upload_to_s3(output_path, S3_BUCKET_NAME)
            if s3_object_name:
                pre_signed_url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': S3_BUCKET_NAME, 'Key': s3_object_name},
                    ExpiresIn=24 * 3600
                )

                if recipient_email:
                    email_sent = send_email_with_attachment(recipient_email, output_path, output_filename)
                    if not email_sent:
                        yield f"data: error|Failed to send email\n\n"

                yield f"data: complete|{pre_signed_url}\n\n"
            else:
                yield f"data: error|Failed to upload file to S3\n\n"
        except Exception as e:
            yield f"data: error|{str(e)}\n\n"

    return Response(generate_translation_progress(), content_type="text/event-stream")


@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    """Download a translated file."""
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename, as_attachment=True)




# Schedule periodic S3 and local folder cleanup
scheduler = BackgroundScheduler()
# Cleanup files in the uploads folder every hour
scheduler.add_job(func=delete_old_files, trigger="interval", hours=1, args=[UPLOAD_FOLDER, 1])
# Cleanup old files from S3 bucket every 24 hours
scheduler.add_job(func=delete_old_s3_files, trigger="interval", hours=24, args=[S3_BUCKET_NAME])
# Start the scheduler
scheduler.start()



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
