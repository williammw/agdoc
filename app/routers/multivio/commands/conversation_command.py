"""
Conversation command implementation for the pipeline pattern.
Handles general conversations, greetings, and other casual interactions.
"""
from .base import Command, CommandFactory
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

@CommandFactory.register("conversation")
class ConversationCommand(Command):
    """Command for handling general conversations and greetings."""
    
    async def can_execute(self, context: Dict[str, Any]) -> bool:
        """
        Determine if this command should execute based on context.
        """
        # Check if conversation is in the intents
        intents = context.get("intents", {})
        if "conversation" in intents:
            return intents["conversation"]["confidence"] > 0.3
            
        # Check if general knowledge with no other intents
        if "general_knowledge" in intents and len(intents) == 1:
            return True
            
        # Check message for very short inputs
        message = context.get("message", "")
        if not message:
            return False
            
        # Very short messages are likely greetings or simple questions
        return len(message.strip()) < 15
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the conversation command.
        """
        # Get the message from context
        message = context.get("message", "")
        intents = context.get("intents", {})
        
        logger.info(f"ConversationCommand executing with message: '{message}'")
        
        # Check if this is a greeting
        is_greeting = False
        greeting_types = ["hello", "hi", "hey", "greetings", "good morning", "good afternoon", 
                         "good evening", "hola", "bonjour", "ciao"]
        
        if any(greeting in message.lower() for greeting in greeting_types):
            is_greeting = True
            
        # Prepare system prompt based on message type
        if is_greeting:
            system_prompt = """
            The user has sent you a greeting. Respond in a friendly, conversational manner.
            Keep your response concise and welcoming, and ask how you can help them today.
            """
        else:
            system_prompt = """
            The user is having a general conversation with you. Respond naturally and helpfully.
            If their message is very short or unclear, politely ask for clarification about what 
            they'd like help with today.
            
            Remember that this is a social media management platform, so they might be looking for
            help with content creation, post scheduling, analytics, or other social media tasks.
            """
        
        # Add the conversation system prompt to the context
        if "system_prompts" not in context:
            context["system_prompts"] = []
            
        context["system_prompts"].append({
            "type": "conversation",
            "content": system_prompt
        })
        
        # Add to general results collection
        context["results"].append({
            "type": "conversation",
            "query": message,
            "is_greeting": is_greeting
        })
        
        return context
