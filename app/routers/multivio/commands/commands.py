"""
Import all commands to register them with the CommandFactory.
This file can be imported in places where all commands need to be available.
"""

from .web_search_command import WebSearchCommand
from .image_generation_command import ImageGenerationCommand
from .social_media_command import SocialMediaCommand
from .puppeteer_command import PuppeteerCommand
from .general_knowledge_command import GeneralKnowledgeCommand
