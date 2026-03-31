"""Conversation management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models import (
    ConversationMeta,
    MessageMeta,
    create_conversation,
    delete_conversation,
    get_conversation,
    get_messages,
    list_conversations,
    update_conversation_title,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("/", response_model=ConversationMeta)
async def create_conv(title: str = "New Conversation"):
    return create_conversation(title=title)


@router.get("/", response_model=list[ConversationMeta])
async def list_convs():
    return list_conversations()


@router.get("/{conv_id}", response_model=ConversationMeta)
async def get_conv(conv_id: str):
    conv = get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.get("/{conv_id}/messages", response_model=list[MessageMeta])
async def get_conv_messages(conv_id: str):
    conv = get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return get_messages(conv_id)


@router.patch("/{conv_id}")
async def rename_conv(conv_id: str, title: str):
    conv = get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    update_conversation_title(conv_id, title)
    return {"message": "Updated"}


@router.delete("/{conv_id}")
async def delete_conv(conv_id: str):
    conv = get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    delete_conversation(conv_id)
    return {"message": "Deleted"}
