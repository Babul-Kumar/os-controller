import pyautogui
import os
from utils.helpers import setup_logger

logger = setup_logger(__name__)

class VisionAutomator:
    # Get the path to the ai_assistant/assets folder
    ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    
    @staticmethod
    def click_icon(icon_name: str, confidence=0.9) -> bool:
        """
        Finds an icon on the screen using computer vision and clicks it.
        Requires opencv-python to be installed for confidence matching.
        """
        if not os.path.exists(VisionAutomator.ASSETS_DIR):
            os.makedirs(VisionAutomator.ASSETS_DIR)
            
        img_path = os.path.join(VisionAutomator.ASSETS_DIR, f"{icon_name}.png")
        
        if not os.path.exists(img_path):
            logger.error(f"Missing vision asset: {img_path}")
            return False
            
        try:
            logger.info(f"Scanning screen for {icon_name}.png...")
            # Locate the center of the image on the screen
            location = pyautogui.locateCenterOnScreen(img_path, confidence=confidence)
            
            if location:
                pyautogui.click(location)
                logger.info(f"✅ Found and clicked {icon_name} at {location}")
                return True
            else:
                logger.warning(f"❌ Could not find {icon_name} on the screen.")
                return False
        except pyautogui.ImageNotFoundException:
            logger.warning(f"❌ Could not find {icon_name} on the screen.")
            return False
        except Exception as e:
            logger.error(f"Vision error for {icon_name}: {e}")
            return False
