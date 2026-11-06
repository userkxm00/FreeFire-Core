from app import app, require_api_key_configured

# Explicit WSGI startup validation: refuse to run if API_KEY is missing or invalid
require_api_key_configured()

if __name__ == '__main__':
    # Production entry point: debug should be disabled by default
    app.run(debug=False)
