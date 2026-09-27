-- Run once from inside the VPC (never expose RDS publicly to do this).
CREATE DATABASE IF NOT EXISTS insurance_portal;

USE insurance_portal;

CREATE TABLE IF NOT EXISTS uploaded_files (
    id INT AUTO_INCREMENT PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    content_type VARCHAR(100),
    upload_timestamp DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Verification query after an upload:
-- SELECT * FROM uploaded_files ORDER BY upload_timestamp DESC LIMIT 5;
