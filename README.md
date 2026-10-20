# Student File Upload (Flask + S3)

Students open `/`, enter name + student ID, attach files, and send.
Staff open `/admin` (password protected) to search, download and delete submissions.

## Where data is stored (S3 only, nothing kept on the server)
    uploads/<id>.<ext>      the uploaded file (encrypted at rest, AES256)
    submissions/<id>.json   the submission record: student name, student ID, course,
                            original file name, size, upload time
Downloads use short-lived (5 min) presigned S3 links, so the bucket can stay private.

## 1. Create the S3 bucket
Create a private bucket (Block all public access = ON) in the same region as your EB environment.

## 2. Give Elastic Beanstalk access
IAM > Roles > `aws-elasticbeanstalk-ec2-role` > Add permissions > Create inline policy > JSON.
Paste `iam-s3-policy.json` and replace YOUR-BUCKET-NAME with your bucket name.

## 3. Deploy
Zip the CONTENTS of this folder (application.py must be at the zip root):
    zip -r ../student-upload-eb.zip . -x ".venv/*" "data/*"
EB console > Create application > Platform: Python (3.11+, Amazon Linux 2023) > upload the zip.
Then set Environment properties (Configuration > Updates, monitoring, and logging):
    S3_BUCKET           = your bucket name
    AWS_DEFAULT_REGION  = your bucket's region (e.g. ap-south-1)
    ADMIN_PASSWORD      = a strong password
The app refuses to start if S3_BUCKET is missing (REQUIRE_S3=true in .ebextensions).
Health check URL: /health  (shows "storage": "s3" when connected to S3).

## Run locally
    ./run_local.sh        (Windows: run_local.bat)
    Open http://127.0.0.1:5000   |   admin: /admin  (user admin, password admin123)
Without S3_BUCKET, local runs save to ./data. To test against real S3 locally, run
`aws configure` first, then set S3_BUCKET and AWS_DEFAULT_REGION before starting.

## Settings
S3_BUCKET, AWS_DEFAULT_REGION, ADMIN_USERNAME, ADMIN_PASSWORD, MAX_UPLOAD_MB (default 20),
REQUIRE_S3, DATA_DIR (local dev only). If you raise MAX_UPLOAD_MB above ~24, also raise
client_max_body_size in .platform/nginx/conf.d/upload.conf.
Allowed file types: edit ALLOWED_EXTENSIONS in application.py.
