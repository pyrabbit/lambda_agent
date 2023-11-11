import io
import json
import os
import subprocess
import sys
import time

import pytest
import structlog
from openai import OpenAI
from openai.types.beta import Thread
from openai.types.beta.threads import Run

OPENAI_ASSISTANT_ID = "asst_RwXjODGNixFm1R4pfATK1546"

client = OpenAI()

logger = structlog.get_logger()


def start_chat(thread: Thread):
    message = input("You: ")

    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=message
    )

    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=OPENAI_ASSISTANT_ID
    )

    print("Waiting for response...")
    while run.status in ["queued", "in_progress"]:
        run = handle_run(run)

    logger.info(f"Exited Run Loop with Status: {run.status}")
    if run.status == "completed":
        messages = client.beta.threads.messages.list(
            thread_id=thread.id,
            limit=5
        )

        response = messages.data[0].content[0]
        print(f"Lambda Architect: {response.text.value}")


def handle_run(run: Run) -> Run:
    while run.status in ["queued", "in_progress"]:
        print(f"Run Status: {run.status}")
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        time.sleep(3)

    if run.status == "requires_action" and run.required_action.type == "submit_tool_outputs":
        tool_outputs = handle_required_actions(run)

        logger.info("Returning tool output results to OpenAI...")
        run = client.beta.threads.runs.submit_tool_outputs(
            thread_id=run.thread_id,
            run_id=run.id,
            tool_outputs=tool_outputs
        )
    return run


def handle_required_actions(run: Run) -> list[dict]:
    """
    Processes function call requests from OpenAI Assistant
    :param run:
    :return: A list of tool output results to be sent back to OpenAI for processing
    """
    tool_outputs = []
    for tool_call in run.required_action.submit_tool_outputs.tool_calls:
        logger.info(f"Calling Function: {tool_call.function.name}")
        try:
            function_to_call = globals()[tool_call.function.name]
            arguments = json.loads(tool_call.function.arguments)

            output = function_to_call(**arguments)
            tool_outputs.append({"tool_call_id": tool_call.id, "output": output})
        except Exception as e:
            logger.error(f"Error Calling Function: {tool_call.function.name}: {e}")
            error_message = "An error occurred but we do not have an error message to report."
            if hasattr(e, "message"):
                error_message = e.message
            elif hasattr(e, "strerror"):
                error_message = e.strerror
            tool_outputs.append({"tool_call_id": tool_call.id, "output": error_message})
    return tool_outputs


def create_file(filepath: str, content: str) -> str:
    """
    Creates a file and writes it to a path
    :param filepath:
    :param content:
    :return: A success message for the created file
    """
    # Extract the directory name from the filepath
    logger.info(f"Creating {filepath}...")
    directory = os.path.dirname(filepath)

    # If the directory is not empty, create necessary folders
    if directory:
        os.makedirs(directory, exist_ok=True)

    # Open the file in write mode, which will create it if it does not exist
    with open(filepath, 'w') as file:
        # Write the content to the file
        file.write(content)

    return f"Successfully created file {filepath}"


def read_file(filepath: str) -> str:
    """
    Reads a file at a given path.

    :param filepath: The path including the filename of the file to be read.
    :return: The content of the file as a string.
    """
    logger.info(f"Reading {filepath}...")
    with open(filepath, 'r') as file:
        return file.read()


def list_files(path: str) -> str:
    """
    Recursively list files at a given path and return their full paths.

    :param path: The path where you want to discover a list of files.
    :return: A line delimited string of full paths to files found in the specified path and its subdirectories.
    """
    logger.info(f"Listing {path}...")
    file_paths = []
    for root, dirs, files in os.walk(path):
        for file in files:
            file_paths.append(os.path.join(root, file))
    return "\n".join(file_paths)


def run_tests() -> str:
    # Create a buffer to capture output
    output_buffer = io.StringIO()

    # Save the original stdout and stderr
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    try:
        # Redirect stdout and stderr to the buffer
        sys.stdout = output_buffer
        sys.stderr = output_buffer

        # Run pytest and capture the output
        pytest.main([])

    finally:
        # Restore original stdout and stderr
        sys.stdout = original_stdout
        sys.stderr = original_stderr

    # Get the captured output
    captured_output = output_buffer.getvalue()

    # Close the buffer
    output_buffer.close()

    return captured_output


def run_command(command):
    """
    Runs a given command on the user's system.

    :param command: The command to be run from the user's system.
    :type command: str
    :return: The output of the command.
    """
    # Ensure the command is safely formatted
    logger.info(f"Running command {command}")

    result = subprocess.run(command, check=True, text=True, capture_output=True)
    return result.stderr if result.stderr else result.stdout


if __name__ == '__main__':
    thread = client.beta.threads.create()

    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=f"The root path of the SAM application can be found at '{os.getcwd()}'. "
                f"The current working directory is '{os.getcwd()}'."
    )

    while True:
        start_chat(thread)
