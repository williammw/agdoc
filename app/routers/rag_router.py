# import os
# import shutil
# from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
# from pydantic import BaseModel
# from openai import OpenAI
# from app.dependencies import get_current_user, verify_token
# from typing import List
# import json
# from dotenv import load_dotenv

# router = APIRouter()

# # Load environment variables
# load_dotenv()
# client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))


# class QueryModel(BaseModel):
#     question: str


# # Step 1: Create a new assistant with file search enabled
# assistant = client.beta.assistants.create(
#     name="Financial Analyst Assistant",
#     instructions="You are an expert financial analyst. Use your knowledge base to answer questions about audited financial statements.",
#     model="gpt-4o",
#     tools=[{"type": "file_search"}]
# )

# # Step 2: Endpoint to upload files and add them to a Vector Store


# @router.post("/upload/")
# async def upload_file(file: UploadFile = File(...), user=Depends(get_current_user)):
#     try:
#         # Save the file locally
#         file_location = f"files/{file.filename}"
#         with open(file_location, "wb") as buffer:
#             shutil.copyfileobj(file.file, buffer)

#         # Create a vector store and upload the file
#         vector_store = client.beta.vector_stores.create(
#             name="Financial Statements")
#         file_streams = [open(file_location, "rb")]
#         file_batch = client.beta.vector_stores.file_batches.upload_and_poll(
#             vector_store_id=vector_store.id, files=file_streams
#         )

#         # Update the assistant to use the new vector store
#         client.beta.assistants.update(
#             assistant_id=assistant.id,
#             tool_resources={"file_search": {
#                 "vector_store_ids": [vector_store.id]}}
#         )

#         return {"info": f"File '{file.filename}' uploaded and processed.", "vector_store_id": vector_store.id}
#     except Exception as e:
#         raise HTTPException(
#             status_code=500, detail=f"Error uploading file: {str(e)}")

# # Step 3: Endpoint to ask questions


# @router.post("/ask/")
# async def ask_question(query: QueryModel, vector_store_id: str = Query(...)):
#     try:
#         # Create a thread and attach the vector store
#         thread = client.beta.threads.create(
#             messages=[
#                 {
#                     "role": "user",
#                     "content": query.question,
#                     "attachments": [
#                         {"file_id": vector_store_id, "tools": [
#                             {"type": "file_search"}]}
#                     ],
#                 }
#             ]
#         )

#         # Step 5: Create a run and check the output
#         class EventHandler(client.AssistantEventHandler):
#             def on_text_created(self, text) -> None:
#                 print(f"\nassistant > {text}", flush=True)

#             def on_tool_call_created(self, tool_call):
#                 print(f"\nassistant > {tool_call.type}\n", flush=True)

#             def on_message_done(self, message) -> None:
#                 message_content = message.content[0].text
#                 annotations = message_content.annotations
#                 citations = []
#                 for index, annotation in enumerate(annotations):
#                     message_content.value = message_content.value.replace(
#                         annotation.text, f"[{index}]"
#                     )
#                     if file_citation := getattr(annotation, "file_citation", None):
#                         cited_file = client.files.retrieve(
#                             file_citation.file_id)
#                         citations.append(f"[{index}] {cited_file.filename}")

#                 print(message_content.value)
#                 print("\n".join(citations))

#         with client.beta.threads.runs.stream(
#             thread_id=thread.id,
#             assistant_id=assistant.id,
#             instructions="Please address the user as Jane Doe. The user has a premium account.",
#             event_handler=EventHandler(),
#         ) as stream:
#             stream.until_done()

#         return {"response": "Run completed successfully."}
#     except Exception as e:
#         raise HTTPException(
#             status_code=500, detail=f"Error generating response: {str(e)}")
