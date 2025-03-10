from __future__ import annotations

import contextlib
import json
import logging
import os

import azure.identity.aio
import fastapi
import openai
import sqlalchemy.exc
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from environs import Env
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .globals import global_storage
from .postgres_models import Base, Item


@contextlib.asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    # setup db engine
    load_dotenv(override=True)

    POSTGRES_HOST = os.environ["POSTGRES_HOST"]
    POSTGRES_USERNAME = os.environ["POSTGRES_USERNAME"]
    POSTGRES_DATABASE = os.environ["POSTGRES_DATABASE"]

    if POSTGRES_HOST.endswith(".database.azure.com"):
        print("Authenticating to Azure Database for PostgreSQL using Azure Identity...")
        azure_credential = DefaultAzureCredential()
        token = azure_credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
        POSTGRES_PASSWORD = token.token
    else:
        POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]

    DATABASE_URI = f"postgresql+asyncpg://{POSTGRES_USERNAME}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}/{POSTGRES_DATABASE}"
    # Specify SSL mode if needed
    if POSTGRES_SSL := os.environ.get("POSTGRES_SSL"):
        DATABASE_URI += f"?ssl={POSTGRES_SSL}"

    engine = create_async_engine(
        DATABASE_URI,
        echo=False,
    )
    async with engine.begin() as conn:
        # Create pgvector extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Create all tables (and indexes) defined in this model in the database
        await conn.run_sync(Base.metadata.create_all)

    async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session_maker() as session:
        # Insert the items from the JSON file into the database
        current_dir = os.path.dirname(os.path.realpath(__file__))
        with open(os.path.join(current_dir, "catalog.json")) as f:
            catalog_items = json.load(f)
            for catalog_item in catalog_items:
                # check if item already exists
                item = await session.execute(select(Item).filter(Item.id == catalog_item["Id"]))
                if item.scalars().first():
                    continue
                item = Item(
                    id=catalog_item["Id"],
                    type=catalog_item["Type"],
                    brand=catalog_item["Brand"],
                    name=catalog_item["Name"],
                    description=catalog_item["Description"],
                    price=catalog_item["Price"],
                    embedding=catalog_item["Embedding"],
                )
                session.add(item)
            try:
                await session.commit()
            except sqlalchemy.exc.IntegrityError:
                pass
    global_storage.engine = engine
    global_storage.async_session_maker = async_session_maker

    OPENAI_CHAT_HOST = os.getenv("OPENAI_CHAT_HOST")
    if OPENAI_CHAT_HOST == "azure":
        token_provider = azure.identity.get_bearer_token_provider(
            azure.identity.DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        global_storage.openai_chat_client = openai.AsyncAzureOpenAI(
            api_version=os.getenv("AZURE_OPENAI_VERSION"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            azure_ad_token_provider=token_provider,
            azure_deployment=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        )
        global_storage.openai_chat_model = os.getenv("AZURE_OPENAI_CHAT_MODEL")
    elif OPENAI_CHAT_HOST == "ollama":
        global_storage.openai_chat_client = openai.AsyncOpenAI(
            base_url=os.getenv("OLLAMA_ENDPOINT"),
            api_key="nokeyneeded",
        )
        global_storage.openai_chat_model = os.getenv("OLLAMA_CHAT_MODEL")
    else:
        global_storage.openai_chat_client = openai.AsyncOpenAI(api_key=os.getenv("OPENAICOM_KEY"))
        global_storage.openai_chat_model = os.getenv("OPENAICOM_CHAT_MODEL")

    OPENAI_EMBED_HOST = os.getenv("OPENAI_EMBED_HOST")
    if OPENAI_EMBED_HOST == "azure":
        token_provider = azure.identity.get_bearer_token_provider(
            azure.identity.DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        global_storage.openai_embed_client = openai.AsyncAzureOpenAI(
            api_version=os.getenv("AZURE_OPENAI_VERSION"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            azure_ad_token_provider=token_provider,
            azure_deployment=os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT"),
        )
        global_storage.openai_embed_model = os.getenv("AZURE_OPENAI_EMBED_MODEL")
    else:
        global_storage.openai_embed_client = openai.AsyncOpenAI(api_key=os.getenv("OPENAICOM_KEY"))
        global_storage.openai_embed_model = os.getenv("OPENAICOM_EMBED_MODEL")

    yield


def create_app():
    env = Env()

    if not os.getenv("RUNNING_IN_PRODUCTION"):
        env.read_env(".env")
        logging.basicConfig(level=logging.DEBUG)

    app = fastapi.FastAPI(docs_url="/", lifespan=lifespan)

    from . import routes  # noqa

    app.include_router(routes.router)

    return app


app = create_app()
