import multiprocessing

bind = "127.0.0.1:8000"
workers = multiprocessing.cpu_count() * 2 + 1
timeout = 120
keepalive = 5
errorlog = "gunicorn_error.log"
accesslog = "gunicorn_access.log"
loglevel = "info" 