from typing import Any

from loguru import logger
from kombu import Connection, Exchange, Queue
from kombu.mixins import ConsumerMixin

from sqc.validation import Validator


class Worker(ConsumerMixin):
    queue = Queue("requests", Exchange("requests", type="fanout", durable=True), "#")

    def __init__(self, validator: Validator):
        self.connection = Connection("amqp://guest:guest@localhost:5672//")
        self.validator = validator

    def get_consumers(self, Consumer, _channel):
        return [Consumer(queues=[self.queue], callbacks=[self.on_message])]

    def on_message(self, body: dict[str, Any], message):
        message.ack()

        if (event_name := body["EventName"]) != "s3:ObjectCreated:Put":
            logger.warning(f"Invalid event name: {event_name}, dropping message")
            return

        request = body["Records"][0]["s3"]["object"]["key"]
        logger.info(f"Got request: {request}")
        self.validator.validate(request)

    def run(self, *args, **kwargs):
        while not self.should_stop:
            with logger.catch():
                super().run(*args, **kwargs)
            self.connection.release()
