import logging

PID_FILE="/harchiverd.pid"
LOG_FILE="/logs/harchiverd.log"
LOG_LEVEL=logging.DEBUG
OUTPUT_DIRECTORY="/images"
WEBSERVICE="http://webrender:8000/webtools/domimage"
PROTOCOLS=["http", "https"]
AMQP_URL="amqp://guest:guest@rabbitmq:5672/%2f"
AMQP_EXCHANGE="heritrix"
AMQP_QUEUE="to-webrender"
AMQP_KEY="to-webrender"
AMQP_OUTLINK_QUEUE="heritrix-outlinks"
