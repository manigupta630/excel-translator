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
    return render_template('index.html')

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

        # Get other form data
        target_lang = request.form.get('target_lang', 'de')
        source_col = request.form.get('source_col', 'source')
        target_col = request.form.get('target_col', 'target')

        try:
            # Load Excel file
            df = pd.read_excel(filepath)

            # Check if source column exists
            if source_col not in df.columns:
                return jsonify({
                    "status": "error",
                    "message": f"Source column '{source_col}' not found in the file.",
                    "available_columns": list(df.columns)
                }), 400

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
                    print(f"Error translating '{text}': {e}")
                    translated_text.append("Error")

            # Add translations to a new column
            df[target_col] = translated_text

            # Save output file
            output_filename = f"translated_{filename}"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            df.to_excel(output_path, index=False)

            return jsonify({
                "status": "success",
                "message": "File translated successfully.",
                "download_url": f"/download/{output_filename}"
            })

        except Exception as e:
            return jsonify({"status": "error", "message": f"Error processing file: {e}"}), 500

    return jsonify({"status": "error", "message": "Invalid file type"}), 400

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
