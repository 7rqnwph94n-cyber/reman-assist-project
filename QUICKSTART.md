# Quickstart Guide

## Development Mode (Local Testing)

### 1. Run Database Migrations
```bash
# Make sure you're in the project directory
cd /Users/richbrotherton/project/reman_app_current/reman_app_v1.1_gold_standard

# Activate virtual environment
source .venv/bin/activate  # or: .venv/Scripts/activate on Windows

# Run migrations
flask db upgrade
```

### 2. Start Development Server

**Option A: Flask Development Server** (recommended for development)
```bash
flask run --debug --port 5001
```

**Option B: Gunicorn** (for production-like testing)
```bash
gunicorn -w 1 -b 127.0.0.1:8000 --reload 'app:create_app()'
```

### 3. Access the Application
Open your browser to: http://localhost:5001 (or http://localhost:8000 if using gunicorn)

---

## Production Deployment

### 1. Set Environment Variables
```bash
# Generate a secure secret key
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"

# Database (PostgreSQL recommended for production)
export DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/reman_db"

# Upload folder (must be writable by web server)
export UPLOAD_FOLDER="/var/www/reman_app/uploads"

# Configuration
export FLASK_CONFIG="production"
export APP_ENV="production"

# Optional: Redis for login throttling
export REDIS_URL="redis://localhost:6379/0"
```

### 2. Create Upload Directory
```bash
# Create directory
sudo mkdir -p /var/www/reman_app/uploads

# Set ownership (replace 'www-data' with your web server user)
sudo chown -R www-data:www-data /var/www/reman_app/uploads

# Set permissions
sudo chmod 755 /var/www/reman_app/uploads
```

### 3. Run Migrations
```bash
flask db upgrade
```

### 4. Start with Gunicorn
```bash
gunicorn -w 4 -b 0.0.0.0:8000 'app:create_app()'
```

### 5. Configure Nginx (Reverse Proxy)

Create `/etc/nginx/sites-available/reman-app`:
```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL certificates (use Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Security headers (redundant with app headers, but good practice)
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # File upload limit (match application limit)
    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Increase timeouts for long-running requests
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # Serve static files directly (optional optimization)
    location /static/ {
        alias /path/to/reman_app/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

Enable and restart:
```bash
sudo ln -s /etc/nginx/sites-available/reman-app /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## Systemd Service (Auto-start on Boot)

Create `/etc/systemd/system/reman-app.service`:
```ini
[Unit]
Description=Reman Application
After=network.target postgresql.service redis.service

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/var/www/reman_app
Environment="PATH=/var/www/reman_app/.venv/bin"
Environment="SECRET_KEY=your-secret-key-here"
Environment="DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/reman_db"
Environment="UPLOAD_FOLDER=/var/www/reman_app/uploads"
Environment="FLASK_CONFIG=production"
Environment="APP_ENV=production"
Environment="REDIS_URL=redis://localhost:6379/0"
ExecStart=/var/www/reman_app/.venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 'app:create_app()'
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable reman-app
sudo systemctl start reman-app
sudo systemctl status reman-app
```

---

## Troubleshooting

### "Permission denied" errors
- **Development**: The app now automatically falls back to `./uploads` directory
- **Production**: Pre-create `/var/www/reman_app/uploads` with proper permissions

### Application won't start
1. Check logs: `sudo journalctl -u reman-app -f`
2. Verify environment variables are set
3. Test database connection: `psql $DATABASE_URL`
4. Check upload folder permissions

### Database errors
```bash
# Check current migration status
flask db current

# If out of sync, upgrade
flask db upgrade
```

### Worker boot errors with Gunicorn
- Ensure all environment variables are set BEFORE starting gunicorn
- Check that virtual environment is activated
- Verify Python version compatibility (3.12+ recommended)

---

## Quick Commands Reference

```bash
# Development
flask run --debug --port 5001

# Run migrations
flask db upgrade

# Create admin user
flask create-admin -u admin@example.com -p YourPassword123!

# Check application health
curl http://localhost:5001/health

# View version info
curl http://localhost:5001/version
```

---

## Next Steps

1. ✅ Application is now ready to run
2. Set up monitoring (Sentry, New Relic, or Datadog)
3. Configure automated backups for database and uploads
4. Set up CI/CD pipeline
5. Review [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) for full checklist
