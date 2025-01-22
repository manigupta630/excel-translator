import os
import pandas as pd
import time
from flask import Flask, request, jsonify, send_from_directory, render_template, Response
from werkzeug.utils import secure_filename
from deep_translator import GoogleTranslator
from flask_cors import CORS  # Ensure this is imported after installing flask-cors

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS after the app is defined

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xlsx'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html', source_lang='en', target_lang='de')

@app.route('/upload', methods=['POST'])
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

        # Load the Excel file into a pandas DataFrame
        df = pd.read_excel(filepath)
        total_rows = df.shape[0]
        total_columns = df.shape[1]
        column_names = list(df.columns)

        return jsonify({
            "status": "success",
            "message": "File uploaded successfully.",
            "file_info": {
                "total_rows": total_rows,
                "total_columns": total_columns,
                "column_names": column_names
            },
            "file_path": filepath
        }), 200

    return jsonify({"status": "error", "message": "Invalid file type. Please upload an Excel file."}), 400

@app.route('/translate_progress', methods=['POST'])
def translate_progress():
    # Retrieve file path and target language from the request
    file_path = request.json.get("file_path")
    target_lang = request.json.get("target_lang", "de")  # Default target language is 'de'

    if not file_path or not os.path.exists(file_path):
        return jsonify({"status": "error", "message": "Invalid or missing file path."}), 400

    def generate_translation_progress():
        try:
            df = pd.read_excel(file_path)

            # Default source and target columns
            source_col = 'Source: en'
            target_col = 'Target: de'

            translated_text = []
            total_rows = len(df)
            for idx, text in enumerate(df[source_col], start=1):
                try:
                    if pd.isna(text) or text == "":
                        translated_text.append("")  # Handle blank rows
                    else:
                        translated = GoogleTranslator(source="auto", target=target_lang).translate(text)
                        translated_text.append(translated)
                except Exception as e:
                    translated_text.append("Error")
                    print(f"Error translating '{text}': {e}")

                # Send progress update to the client
                yield f"data: {int((idx / total_rows) * 100)}\n\n"
                time.sleep(0.1)  # Simulate processing time for demonstration

            # Save the translated file
            df[target_col] = translated_text
            output_filename = f"translated_{os.path.basename(file_path)}"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            df.to_excel(output_path, index=False)

            # Indicate completion
            yield f"data: complete|/download/{output_filename}\n\n"
        except Exception as e:
            yield f"data: error|{str(e)}\n\n"

    return Response(generate_translation_progress(), content_type="text/event-stream")


@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename, as_attachment=True)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
