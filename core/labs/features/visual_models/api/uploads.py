from django.core.files.uploadhandler import FileUploadHandler
from rest_framework.exceptions import APIException

from ..validation import MAX_BYTES


class ModelPayloadTooLarge(APIException):
    status_code = 413
    default_detail = "Use a GLB file up to 15 MB."
    default_code = "payload_too_large"


class ModelSizeLimit(FileUploadHandler):
    """Reject oversized uploads while receiving chunks, before reading the entire file."""

    def __init__(self, request=None):
        super().__init__(request)
        self.received = 0

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > MAX_BYTES:
            raise ModelPayloadTooLarge
        return raw_data

    def file_complete(self, file_size):
        return None
