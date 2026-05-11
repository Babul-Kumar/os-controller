import pyautogui
import time
import math
import pygetwindow as gw
from utils.helpers import setup_logger

logger = setup_logger(__name__)

class MouseAutomator:
    @staticmethod
    def draw_indian_flag():
        """Draws a basic representation of the Indian National Flag in MS Paint."""
        logger.info("Drawing Indian National Flag")
        # Wait a moment for the canvas to be ready
        time.sleep(2)
        
        screen_width, screen_height = pyautogui.size()
        cx, cy = screen_width // 2, screen_height // 2
        
        width = 400
        height = 80
        
        # In modern Windows 11 Paint, the canvas is centered. 
        # Start drawing relative to the center to guarantee we hit the white canvas.
        start_x = int(cx - (width / 2))
        start_y = int(cy - (height * 1.5))
            
        width = 400
        height = 80
        
        # Click on the canvas to ensure it has focus before drawing
        pyautogui.click(start_x, start_y)
        time.sleep(0.5)
        
        # Select Pencil/Brush tool (default in paint is usually pencil)
        # We will just draw the outlines
        
        # Saffron rectangle (Top)
        MouseAutomator._draw_rect(start_x, start_y, width, height)
        
        # White rectangle (Middle)
        MouseAutomator._draw_rect(start_x, start_y + height, width, height)
        
        # Green rectangle (Bottom)
        MouseAutomator._draw_rect(start_x, start_y + 2 * height, width, height)
        
        # Blue circle (Ashoka Chakra)
        center_x = start_x + width // 2
        center_y = start_y + height + height // 2
        radius = height // 2 - 5
        MouseAutomator._draw_circle(center_x, center_y, radius)
        
        # Ashoka Chakra Spokes (24 spokes = 12 intersecting lines)
        for i in range(12):
            angle = i * (math.pi / 12)
            dx = radius * math.cos(angle)
            dy = radius * math.sin(angle)
            pyautogui.moveTo(center_x - dx, center_y - dy)
            pyautogui.dragTo(center_x + dx, center_y + dy, duration=0.1, button='left')
            
        # Draw Flag Pole
        pole_width = 15
        pole_height = height * 5
        pole_x = start_x - pole_width
        pole_y = start_y - 20 # slightly above the flag
        MouseAutomator._draw_rect(pole_x, pole_y, pole_width, pole_height)
        
        # Draw Stand (Base Steps)
        base_y = pole_y + pole_height
        MouseAutomator._draw_rect(pole_x - 20, base_y, pole_width + 40, 20)
        MouseAutomator._draw_rect(pole_x - 40, base_y + 20, pole_width + 80, 20)
        MouseAutomator._draw_rect(pole_x - 60, base_y + 40, pole_width + 120, 20)
        
        # Move mouse out of the way before scanning
        pyautogui.moveTo(start_x - 50, start_y - 50, duration=0.5)
        
        # --- COLOR FILLING PHASE (Computer Vision) ---
        from automation.vision import VisionAutomator
        
        # 1. Select the Paint Bucket tool
        if VisionAutomator.click_icon("bucket"):
            time.sleep(0.5)
            
            # 2. Fill Saffron (Top)
            if VisionAutomator.click_icon("orange"):
                time.sleep(0.5)
                # Click inside the top rectangle
                pyautogui.click(start_x + width // 2, start_y + height // 2)
                
            # 3. Fill Green (Bottom)
            if VisionAutomator.click_icon("green"):
                time.sleep(0.5)
                # Click inside the bottom rectangle
                pyautogui.click(start_x + width // 2, start_y + 2 * height + height // 2)
                
            # 4. We keep the Chakra white, but we can fill the pole!
            if VisionAutomator.click_icon("brown") or VisionAutomator.click_icon("black"):
                time.sleep(0.5)
                # Click inside the pole
                pyautogui.click(pole_x + pole_width // 2, pole_y + pole_height // 2)

    @staticmethod
    def _draw_rect(x, y, w, h):
        pyautogui.moveTo(x, y)
        pyautogui.dragTo(x + w, y, duration=0.2, button='left')
        pyautogui.dragTo(x + w, y + h, duration=0.2, button='left')
        pyautogui.dragTo(x, y + h, duration=0.2, button='left')
        pyautogui.dragTo(x, y, duration=0.2, button='left')
        
    @staticmethod
    def _draw_circle(cx, cy, radius):
        # Draw circle using small steps
        steps = 36
        pyautogui.moveTo(cx + radius, cy)
        # Use dragTo for each small segment to ensure it registers as drawing
        px, py = cx + radius, cy
        for i in range(1, steps + 1):
            angle = i * (2 * math.pi / steps)
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            pyautogui.dragTo(x, y, duration=0.02, button='left')
            px, py = x, y
        
    @staticmethod
    def draw_shape(shape_name: str) -> str:
        """Routes to the correct drawing method based on shape name."""
        logger.info(f"Requested to draw: {shape_name}")
        shape_name_lower = shape_name.lower()

        if "flag" in shape_name_lower or "indian" in shape_name_lower:
            MouseAutomator.draw_indian_flag()
            return "✅ Successfully drew the Indian National Flag in Paint."

        elif "circle" in shape_name_lower:
            time.sleep(1)
            screen_width, screen_height = pyautogui.size()
            MouseAutomator._draw_circle(screen_width // 2, screen_height // 2, 100)
            return "✅ Drawn a circle."

        elif "square" in shape_name_lower or "rectangle" in shape_name_lower:
            time.sleep(1)
            screen_width, screen_height = pyautogui.size()
            MouseAutomator._draw_rect(screen_width // 2 - 100, screen_height // 2 - 100, 200, 200)
            return "✅ Drawn a rectangle."

        else:
            # Universal: search assets → PC → web → spiral
            from automation.draw_engine import draw_anything
            return draw_anything(shape_name)
