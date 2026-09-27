import os

import boto3
from flask import Flask, redirect, render_template, request
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

app = Flask(__name__, template_folder=FRONTEND_DIR)
S3_BUCKET = os.environ.get("S3_BUCKET", "insurance-portal-uploads-file")
s3 = boto3.client("s3")  # uses EC2 instance role — no hardcoded keys

MAX_FILE_BYTES = 3 * 1024 * 1024  # 3 MB
# Extra room for multipart form headers around the file body.
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_BYTES + (64 * 1024)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if not file or file.filename == "":
        return "No file selected", 400

    filename = secure_filename(file.filename)
    if not filename:
        return "Invalid file name", 400

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_BYTES:
        return file_too_large(None)

    s3.upload_fileobj(
        file,
        S3_BUCKET,
        filename,
        ExtraArgs={"ContentType": file.content_type or "application/octet-stream"},
    )
    return f"File '{filename}' uploaded successfully!"


@app.errorhandler(413)
def file_too_large(_error):
    return (
        '<p style="color:#c0392b;">File is too large. Maximum size is 3 MB.</p>'
    ), 413


if __name__ == "__main__":
    # Local dev uses 5000. On EC2, Step 5 starts gunicorn on port 80.
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
