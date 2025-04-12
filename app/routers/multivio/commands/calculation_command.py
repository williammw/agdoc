"""
Calculation command implementation for the pipeline pattern.
Handles basic arithmetic and mathematical queries.
"""
from .base import Command, CommandFactory
from typing import Dict, Any
import logging
import re
import math
import os
from openai import OpenAI

logger = logging.getLogger(__name__)

# Load environment variables
GROK_API_KEY = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
GROK_API_BASE_URL = os.getenv("GROK_API_BASE_URL", "https://api.x.ai/v1")

# Default model to use
DEFAULT_MODEL = "grok-3-mini-beta"

@CommandFactory.register("calculation")
class CalculationCommand(Command):
    """Command for handling basic math calculations."""
    
    async def can_execute(self, context: Dict[str, Any]) -> bool:
        """
        Determine if this command should execute based on context.
        """
        # Check if calculation is in the intents
        intents = context.get("intents", {})
        if "calculation" in intents:
            return intents["calculation"]["confidence"] > 0.3
            
        # Check message for calculation patterns as a backup
        message = context.get("message", "").lower()
        if not message:
            return False
        
        # Check for common math operation patterns
        calculation_patterns = [
            r'\d+\s*[\+\-\*\/\^\%]\s*\d+',  # Basic operations like 10+10
            r'what\s+is\s+\d+\s*[\+\-\*\/\^\%]\s*\d+',  # What is 10+10
            r'calculate\s+\d+\s*[\+\-\*\/\^\%]\s*\d+',  # Calculate 10+10
            r'compute\s+\d+\s*[\+\-\*\/\^\%]\s*\d+',    # Compute 10+10
            r'solve\s+\d+\s*[\+\-\*\/\^\%]\s*\d+',      # Solve 10+10
            r'(\d+)\s*squared',  # 10 squared
            r'square\s+root\s+of\s+(\d+)',  # Square root of 10
            r'cube\s+of\s+(\d+)',  # Cube of 10
            r'(\d+)\s*cubed',  # 10 cubed
            r'factorial\s+of\s+(\d+)',  # Factorial of 10
            r'(\d+)\s*factorial',  # 10 factorial
            r'log\s+of\s+(\d+)',  # Log of 10
            r'sine\s+of\s+(\d+)',  # Sine of 10
            r'cosine\s+of\s+(\d+)',  # Cosine of 10
            r'tangent\s+of\s+(\d+)',  # Tangent of 10
        ]
        
        for pattern in calculation_patterns:
            if re.search(pattern, message):
                return True
                
        return False
    
    def _parse_expression(self, message: str) -> str:
        """
        Extract the mathematical expression from the message.
        """
        # Clean up message and extract the expression
        message = message.lower().strip()
        
        # Handle "what is X" pattern
        if message.startswith(("what is ", "what's ")):
            message = message[8:] if message.startswith("what is ") else message[7:]
        
        # Handle other command patterns
        prefixes = ["calculate ", "compute ", "solve ", "find "]
        for prefix in prefixes:
            if message.startswith(prefix):
                message = message[len(prefix):]
                break
                
        # Remove question marks and other punctuation at the end
        message = re.sub(r'[?!.,;:]$', '', message)
        
        return message
    
    def _evaluate_expression(self, expression: str) -> float:
        """
        Safely evaluate a mathematical expression.
        """
        # Replace common text expressions with symbols
        text_to_symbols = {
            "plus": "+",
            "minus": "-",
            "times": "*",
            "multiplied by": "*",
            "divided by": "/",
            "over": "/",
            "modulo": "%",
            "mod": "%",
            "to the power of": "**",
            "squared": "**2",
            "cubed": "**3",
        }
        
        for text, symbol in text_to_symbols.items():
            expression = expression.replace(text, symbol)
        
        # Handle special math functions
        sqrt_match = re.search(r'square\s+root\s+of\s+(\d+)', expression)
        if sqrt_match:
            return math.sqrt(float(sqrt_match.group(1)))
            
        factorial_match = re.search(r'factorial\s+of\s+(\d+)|(\d+)\s*factorial', expression)
        if factorial_match:
            n = int(factorial_match.group(1) or factorial_match.group(2))
            return math.factorial(n) if n >= 0 else None
            
        # Special case for simple expression like "10+10"
        simple_math_match = re.search(r'(\d+)\s*([\+\-\*\/\^\%])\s*(\d+)', expression)
        if simple_math_match:
            a = float(simple_math_match.group(1))
            op = simple_math_match.group(2)
            b = float(simple_math_match.group(3))
            
            if op == '+':
                return a + b
            elif op == '-':
                return a - b
            elif op in ['*', '×', '·']:
                return a * b
            elif op in ['/', '÷']:
                return a / b if b != 0 else None
            elif op == '^' or op == '**':
                return a ** b
            elif op == '%':
                return a % b if b != 0 else None
                
        # If no patterns matched, try to use eval as a fallback
        # but only with safe operations
        try:
            # Remove any characters that aren't numbers, operators, or whitespace
            safe_expression = re.sub(r'[^0-9\+\-\*\/\(\)\.\s\%]', '', expression)
            return eval(safe_expression)
        except:
            return None
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the calculation command.
        """
        # Get the message from context
        message = context.get("message", "")
        
        logger.info(f"CalculationCommand executing with message: '{message}'")
        
        # Parse the expression from the message
        expression = self._parse_expression(message)
        
        # Try to evaluate the expression with our simple evaluator
        result = self._evaluate_expression(expression)
        
        # For complex calculations, fall back to Grok if our evaluator failed
        if result is None and GROK_API_KEY:
            try:
                # Use Grok-3 for complex calculations
                client = OpenAI(
                    api_key=GROK_API_KEY,
                    base_url=GROK_API_BASE_URL
                )
                
                # Create system prompt for calculation
                system_prompt = """
                You are a mathematical calculation assistant. Your only task is to:
                1. Identify the mathematical calculation being requested
                2. Compute the result
                3. Reply with ONLY the result as a number, nothing else
                
                Don't explain steps or provide any other text. Just return the numerical result.
                """
                
                # Prepare messages
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Calculate: {expression}"}
                ]
                
                # Prepare parameters for the API call
                params = {
                    "model": DEFAULT_MODEL,
                    "messages": messages,
                    "temperature": 0.0,  # Use deterministic output for calculations
                    "max_tokens": 50,     # Results should be short
                    "reasoning_effort": "high"  # Use high reasoning for calculations
                }
                
                # Call the API
                logger.info(f"Using {DEFAULT_MODEL} API for complex calculation: {expression}")
                completion = client.chat.completions.create(**params)
                
                # Get the content from the response
                grok_result = completion.choices[0].message.content.strip()
                
                # Try to convert the result to a number
                try:
                    # Check if the result is a numeric value
                    if re.match(r'^-?\d+(\.\d+)?$', grok_result):
                        result = float(grok_result)
                        # Convert to integer if it's a whole number
                        if result == int(result):
                            result = int(result)
                        logger.info(f"Successfully calculated {expression} = {result} using Grok API")
                    else:
                        # If not numeric, use the text as fallback
                        result_text = grok_result
                        # Set result to None to use our text-based fallback
                        result = None
                except:
                    logger.error(f"Error converting Grok result to number: {grok_result}")
                    # We'll fall back to the text-based response below
                    result = None
            except Exception as e:
                logger.error(f"Error using Grok API for calculation: {str(e)}")
                # Fall back to our default error message
        
        # Format the result
        if result is not None:
            # Convert to integer if it's a whole number
            if result == int(result):
                result = int(result)
                
            result_text = f"The answer to {expression} is {result}."
            calculation_content = f"""
# Mathematical Calculation

{result_text}

To calculate this:
- Expression: {expression}
- Result: {result}
"""
        else:
            result_text = f"I couldn't calculate '{expression}'. Please check the syntax and try again."
            calculation_content = f"""
# Mathematical Calculation

I couldn't evaluate the expression '{expression}'. 

This could be due to:
- Invalid mathematical syntax
- Division by zero
- An operation that's not supported

Please rephrase your calculation request.
"""
        
        # Add to general results collection
        context["results"].append({
            "type": "calculation",
            "expression": expression,
            "result": result,
            "content": calculation_content
        })
        
        # Add the content to context for the response
        context["general_knowledge_content"] = calculation_content
        
        return context
