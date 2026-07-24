import azure.functions as func
import logging
from azure.storage.blob import BlobServiceClient
import os

app = func.FunctionApp()

ALLOWED_PREFIXES = ["assoc", "scan", "report"]

# Container names from environment variables (with defaults)
SOURCE_CONTAINER = os.environ.get("SOURCE_CONTAINER", "from")
DEST_CONTAINER = os.environ.get("DEST_CONTAINER", "togcp")


@app.blob_trigger(arg_name="myblob", path=f"{SOURCE_CONTAINER}/{{year}}/{{month}}/{{day}}/{{filename}}", connection="AzureWebJobsStorage")
def democlonefiles(myblob: func.InputStream):
    """
    Azure Function triggered when a new blob arrives in the 'from' container.
    Only copies files whose name starts with: assoc, scan, or report.
    Copies to the destination container in a separate storage account.
    Preserves the year/month/day folder structure.
    """
    logging.info(f"Blob trigger fired: {myblob.name}, Size: {myblob.length} bytes")

    try:
        # Extract path components: from/year/month/day/filename
        parts = myblob.name.split("/")
        year = parts[1]
        month = parts[2]
        day = parts[3]
        filename = "/".join(parts[4:])

        # Filter: only process files matching allowed prefixes
        if not any(filename.lower().startswith(prefix) for prefix in ALLOWED_PREFIXES):
            logging.info(f"Skipping '{filename}' - does not match prefixes: {ALLOWED_PREFIXES}")
            return

        # Read blob content directly from the trigger
        blob_data = myblob.read()

        # Connect to DESTINATION storage account
        dest_connection_string = os.environ.get("DestinationStorage")
        dest_blob_service_client = BlobServiceClient.from_connection_string(dest_connection_string)

        # Destination container from environment variable (default: togcp)
        dest_container_client = dest_blob_service_client.get_container_client(DEST_CONTAINER)

        # Ensure destination container exists
        try:
            dest_container_client.get_container_properties()
        except Exception:
            logging.info(f"Creating destination container '{DEST_CONTAINER}'")
            dest_container_client.create_container()

        # Preserve folder structure: {dest_container}/year/month/day/filename
        dest_path = f"{year}/{month}/{day}/{filename}"
        dest_blob_client = dest_container_client.get_blob_client(dest_path)
        dest_blob_client.upload_blob(blob_data, overwrite=True)

        logging.info(f"Successfully copied '{filename}' to destination: {DEST_CONTAINER}/{dest_path}")

    except Exception as e:
        logging.error(f"Error processing blob: {str(e)}")
        raise
