import azure.functions as func
import logging
from azure.storage.blob import BlobServiceClient
import os

app = func.FunctionApp()

ALLOWED_PREFIXES = ["assoc", "scan", "report"]


@app.blob_trigger(arg_name="myblob", path="from/{year}/{month}/{day}/{filename}", connection="AzureWebJobsStorage")
def democlonefiles(myblob: func.InputStream):
    """
    Azure Function triggered when a new blob arrives in the 'from' container.
    Only copies files whose name starts with: assoc, scan, or report.
    Copies to the 'togcp' container in a separate destination storage account.
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

        dest_container_client = dest_blob_service_client.get_container_client("togcp")

        # Ensure destination container exists
        try:
            dest_container_client.get_container_properties()
        except Exception:
            logging.info("Creating destination container 'togcp'")
            dest_container_client.create_container()

        # Preserve folder structure: togcp/year/month/day/filename
        dest_path = f"{year}/{month}/{day}/{filename}"
        dest_blob_client = dest_container_client.get_blob_client(dest_path)
        dest_blob_client.upload_blob(blob_data, overwrite=True)

        logging.info(f"Successfully copied '{filename}' to destination storage: togcp/{dest_path}")

    except Exception as e:
        logging.error(f"Error processing blob: {str(e)}")
        raise
