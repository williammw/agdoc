"""
Base classes for the Command Pattern and Pipeline implementation.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Set
import logging
import uuid

logger = logging.getLogger(__name__)

class Command(ABC):
    """
    Base class for all command implementations.
    Each command represents a specific intent that can be processed.
    """
    # Class variable to store command types
    command_types: Set[str] = set()
    
    def __init__(self, name: Optional[str] = None):
        """
        Initialize a command with an optional name.
        """
        self.name = name or self.__class__.__name__
        self.id = str(uuid.uuid4())
        
    @abstractmethod
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the command's functionality and return the updated context.
        
        Args:
            context: The current context containing all data needed for execution
            
        Returns:
            Updated context with command's results
        """
        pass
        
    @abstractmethod
    async def can_execute(self, context: Dict[str, Any]) -> bool:
        """
        Determine if this command should execute based on the current context.
        
        Args:
            context: The current context containing intent information and other data
            
        Returns:
            True if command should execute, False otherwise
        """
        pass
        
    @property
    def command_type(self) -> str:
        """
        Get the type of this command (used for categorizing and grouping commands).
        Default implementation returns the class name.
        """
        return self.__class__.__name__

class Pipeline:
    """
    A pipeline that executes a series of commands in sequence.
    """
    
    def __init__(self, name: str = "DefaultPipeline"):
        """
        Initialize a new pipeline.
        
        Args:
            name: A name for this pipeline for logging purposes
        """
        self.name = name
        self.commands: List[Command] = []
        
    def add_command(self, command: Command) -> 'Pipeline':
        """
        Add a command to the pipeline.
        
        Args:
            command: The command to add
            
        Returns:
            Self for method chaining
        """
        self.commands.append(command)
        return self
        
    async def execute(self, initial_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute all applicable commands in the pipeline.
        
        Args:
            initial_context: The initial context data
            
        Returns:
            Final context after all commands have executed
        """
        context = initial_context.copy()
        
        # Add a results collection to track command outputs
        if "results" not in context:
            context["results"] = []
            
        # Add a pipeline_log for debugging
        if "pipeline_log" not in context:
            context["pipeline_log"] = []
            
        # Execute each command that can run based on the context
        for i, command in enumerate(self.commands):
            try:
                if await command.can_execute(context):
                    logger.info(f"[Pipeline:{self.name}] Executing command ({i+1}/{len(self.commands)}): {command.name}")
                    
                    # Log the command execution start
                    context["pipeline_log"].append({
                        "step": i + 1,
                        "command": command.name,
                        "command_id": command.id,
                        "status": "started"
                    })
                    
                    # Execute the command
                    start_time = __import__('time').time()
                    updated_context = await command.execute(context)
                    end_time = __import__('time').time()
                    execution_time = round(end_time - start_time, 3)
                    
                    # Replace the context
                    context = updated_context
                    
                    # Update the pipeline log with success
                    context["pipeline_log"][-1].update({
                        "status": "completed",
                        "execution_time": execution_time
                    })
                    
                    logger.info(f"[Pipeline:{self.name}] Command {command.name} completed in {execution_time}s")
                else:
                    logger.info(f"[Pipeline:{self.name}] Skipping command: {command.name} (cannot execute)")
            except Exception as e:
                logger.error(f"[Pipeline:{self.name}] Error executing command {command.name}: {str(e)}", exc_info=True)
                
                # Update the pipeline log with failure
                context["pipeline_log"].append({
                    "step": i + 1,
                    "command": command.name,
                    "command_id": command.id,
                    "status": "failed",
                    "error": str(e)
                })
                
                # Add the error to context but continue with next command
                if "errors" not in context:
                    context["errors"] = []
                    
                context["errors"].append({
                    "command": command.name,
                    "command_id": command.id,
                    "error": str(e)
                })
        
        return context

class CommandFactory:
    """
    Factory class for creating and retrieving commands.
    """
    _commands: Dict[str, type] = {}
    
    @classmethod
    def register(cls, command_type: str):
        """
        Decorator for registering command classes.
        
        Args:
            command_type: The type name for this command
        """
        def inner_wrapper(wrapped_class):
            cls._commands[command_type] = wrapped_class
            Command.command_types.add(command_type)
            return wrapped_class
        return inner_wrapper
    
    @classmethod
    def create(cls, command_type: str, **kwargs) -> Command:
        """
        Create a new command instance of the specified type.
        
        Args:
            command_type: The type of command to create
            **kwargs: Additional arguments to pass to the command constructor
            
        Returns:
            New command instance
        """
        if command_type not in cls._commands:
            raise ValueError(f"Unknown command type: {command_type}")
            
        return cls._commands[command_type](**kwargs)
        
    @classmethod
    def get_available_commands(cls) -> List[str]:
        """
        Get a list of all available command types.
        
        Returns:
            List of command type names
        """
        return list(cls._commands.keys())
