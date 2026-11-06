from app import app

if __name__ == '__main__':
    # Production entry point: debug should be disabled by default
    app.run(debug=False)
