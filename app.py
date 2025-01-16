import os
import pandas as pd
from flask import Flask, request, jsonify, send_from_directory, render_template
from werkzeug.utils import secure_filename
from deep_translator import GoogleTranslator

# Initialize Flask app
app = Flask(__name__)

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
    # Check if a file is provided in the request
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part in the request"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No file selected"}), 400

    if file and allowed_file(file.filename):
        # Save the uploaded file to the upload folder
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Load the Excel file into a pandas DataFrame
        try:
            df = pd.read_excel(filepath)
        except Exception as e:
            return jsonify({"status": "error", "message": f"Error reading Excel file: {e}"}), 500

        # Get basic information about the file
        total_rows = df.shape[0]
        total_columns = df.shape[1]
        column_names = list(df.columns)

        # Return the basic file info in the response
        return jsonify({
            "status": "success",
            "message": "File uploaded successfully.",
            "file_info": {
                "total_rows": total_rows,
                "total_columns": total_columns,
                "column_names": column_names
            },
            "file_path": filepath  # Pass the file path for the next step (translation)
        }), 200

    return jsonify({"status": "error", "message": "Invalid file type. Please upload an Excel file."}), 400


@app.route('/translate', methods=['POST'])

def translate_file():
    # Retrieve file path and target language from the request
    file_path = request.json.get("file_path")
    target_lang = request.json.get("target_lang", "de")  # Default target language is 'de'

    if not file_path or not os.path.exists(file_path):
        return jsonify({"status": "error", "message": "Invalid or missing file path."}), 400

    try:
        # Load the Excel file into a pandas DataFrame
        df = pd.read_excel(file_path)

        # Default source and target columns
        source_col = 'Source: en'
        target_col = 'Target: de'

        # Translate content
        translated_text = []
        for text in df[source_col]:
            try:
                if pd.isna(text) or text == "":
                    translated_text.append("")  # Handle blank rows
                else:
                    translated = GoogleTranslator(source="auto", target=target_lang).translate(text)
                    translated_text.append(translated)
            except Exception as e:
                translated_text.append("Error")
                print(f"Error translating '{text}': {e}")

        # Add translations to a new column
        df[target_col] = translated_text

        # Save the translated file
        output_filename = f"translated_{os.path.basename(file_path)}"
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
        df.to_excel(output_path, index=False)

        # Return success response with the download link
        return jsonify({
            "status": "success",
            "message": "File translated successfully.",
            "download_url": f"/download/{output_filename}"
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Error processing file: {e}"}), 500


@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename, as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True)
 