import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))

from web.app import app as application


if __name__ == "__main__":
    from web.app import app
    app.run(debug=True)
