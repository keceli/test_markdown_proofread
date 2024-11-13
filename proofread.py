import os
import sys
import time
import openai
from github import Github
import difflib
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_log,
    after_log
)
import logging
import requests.exceptions

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    retry=retry_if_exception_type((
        openai.APIError,
        openai.APIConnectionError,
        openai.APITimeoutError,
        requests.exceptions.RequestException,
        ConnectionError,
        TimeoutError
    )),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.INFO)
)
def get_openai_response(content):
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that proofreads and corrects markdown text.",
                },
                {
                    "role": "user",
                    "content": f"Proofread and correct the following markdown content:\n\n{content}",
                },
            ],
            temperature=0.0,
            timeout=30,
            request_timeout=30,
        )
        
        if not response or not hasattr(response, 'choices') or not response.choices:
            raise ValueError("Invalid or empty response from OpenAI API")
            
        return response
    except Exception as e:
        logger.error(f"Error in API call: {str(e)}")
        raise

def main():
    files_list_file = sys.argv[1]
    with open(files_list_file, "r") as f:
        files = f.read().splitlines()

    openai.api_key = os.environ["OPENAI_API_KEY"]

    github_token = os.environ["GITHUB_TOKEN"]
    repository = os.environ["GITHUB_REPOSITORY"]
    pr_number = int(os.environ["PR_NUMBER"])

    g = Github(github_token)
    repo = g.get_repo(repository)
    pr = repo.get_pull(pr_number)

    for file_path in files:
        if not os.path.exists(file_path):
            print(f"File {file_path} does not exist.")
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            original_content = f.read()

        # Use OpenAI API to proofread the content
        try:
            # Sanitize the content before sending
            sanitized_content = original_content.encode(
                "utf-8", errors="ignore"
            ).decode("utf-8")

            try:
                logger.info(f"Processing file: {file_path}")
                response = get_openai_response(sanitized_content)
                if not response or not response.choices:
                    logger.error(f"Empty response received for {file_path}")
                    continue
                    
                proofread_content = response.choices[0].message.content
                logger.info(f"Successfully processed {file_path}")
                
            except Exception as api_error:
                logger.error(f"API Error for {file_path}: {str(api_error)}")
                continue

        except Exception as e:
            logger.error(f"Error processing {file_path}: {str(e)}")
            continue

        # Compute the diff
        diff = difflib.unified_diff(
            original_content.splitlines(),
            proofread_content.splitlines(),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )

        diff_text = "\n".join(diff)

        if diff_text:
            # Post the diff as a comment on the PR
            comment_body = (
                f"Suggestions for **{file_path}**:\n\n```diff\n{diff_text}\n```"
            )
            pr.create_issue_comment(comment_body)
        else:
            print(f"No suggestions for {file_path}")


if __name__ == "__main__":
    main()
