# src/element_detector.py
"""
This module finds all selectable elements on a PDF page.

Key concepts:
- Text blocks: Rectangular areas containing text
- Images: Embedded pictures in the PDF
- Bounding box (bbox): Rectangle coordinates (x0, y0, x1, y1)
"""

# gui_app/services/element_detector.py
from .pdf_loader import PDFLoader  # Only needed for the test section
from dataclasses import dataclass
from typing import List


@dataclass
class Element:
    """
    Represents a selectable element (text block or image).
    
    A dataclass automatically creates __init__, __repr__, etc.
    This is a simpler way to create classes that just hold data.
    """
    page_num: int
    element_type: str  # 'text' or 'image'
    bbox: tuple  # (x0, y0, x1, y1) coordinates
    content: str  # text content or image description


class ElementDetector:
    """Detect all elements on a PDF page."""
    
    def __init__(self, page, page_num: int):
        """
        Initialize detector for a specific page.
        
        Args:
            page: PyMuPDF Page object (from PDFLoader)
            page_num: Page number (0-indexed)
        """
        self.page = page
        self.page_num = page_num
    
    def get_text_blocks(self) -> List[Element]:
        """
        Extract all text blocks from the page.
        
        Returns:
            List of Element objects (type='text')
        """
        # page.get_text("blocks") returns list of text blocks
        # Each block: (x0, y0, x1, y1, "text content", block_no, block_type)
        blocks = self.page.get_text("blocks")
        
        elements = []
        for block in blocks:
            x0, y0, x1, y1 = block[:4]
            text = block[4].strip()
            
            # Skip empty blocks
            if text:
                elem = Element(
                    page_num=self.page_num,
                    element_type='text',
                    bbox=(x0, y0, x1, y1),
                    content=text
                )
                elements.append(elem)
        
        return elements
    
    def get_images(self) -> List[Element]:
        """
        Extract all images from the page.
        
        Returns:
            List of Element objects (type='image')
        """
        # page.get_images() returns list of image info
        # Each: (xref, smask, width, height, bpc, colorspace, alt, name, filter)
        images = self.page.get_images()
        
        elements = []
        for img_info in images:
            xref = img_info[0]  # Cross-reference ID
            
            # Get image rectangle (position on page)
            try:
                img_rects = self.page.get_image_rects(xref)
                if img_rects:
                    rect = img_rects[0]
                    
                    # Handle Rect object - convert to tuple
                    # Rect objects support tuple() conversion
                    try:
                        # Try to convert to tuple (works for Rect objects)
                        rect_tuple = tuple(rect)
                        bbox = rect_tuple
                    except:
                        # If it's already a tuple/list, use as-is
                        bbox = tuple(rect)
                    
                    elem = Element(
                        page_num=self.page_num,
                        element_type='image',
                        bbox=bbox,
                        content=f"Image (ID: {xref})"
                    )
                    elements.append(elem)
                    
            except Exception as e:
                print(f"Warning: Could not get image rect for xref={xref}: {e}")
                # Skip this image - don't add it to elements
        
        return elements 
    def get_all_elements(self) -> List[Element]:
        """Get all elements (text + images) on the page."""
        text_elements = self.get_text_blocks()
        image_elements = self.get_images()
        
        # Combine both lists
        return text_elements + image_elements

    def get_images_with_data(self) -> List[dict]:
        """
        Extract image data from the page.
        
        Returns:
            List of dicts with image info and pixmap data
        """
        images = self.page.get_images()
        image_data = []
        
        for img_info in images:
            xref = img_info[0]
            
            try:
                # Extract the actual image using the page's parent document
                # In newer PyMuPDF, use page.parent instead of page.doc
                pix = fitz.Pixmap(self.page.parent, xref)
                
                # Convert CMYK to RGB if needed
                if pix.n - pix.alpha > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                
                # Get image rectangle
                img_rects = self.page.get_image_rects(xref)
                rect = img_rects[0] if img_rects else None
                
                # Convert Rect to tuple
                bbox = tuple(rect) if rect else None
                
                image_data.append({
                    'xref': xref,
                    'width': pix.width,
                    'height': pix.height,
                    'bbox': bbox,
                    'pixmap': pix
                })
                
            except Exception as e:
                print(f"Warning: Could not extract image {xref}: {e}")
        
        return image_data

# Test it
if __name__ == "__main__":
    from pdf_loader import PDFLoader
    
    with PDFLoader("test.pdf") as loader:
        page = loader.get_page(0)
        detector = ElementDetector(page, 0)
        
        elements = detector.get_all_elements()
        
        print(f"Found {len(elements)} elements:")
        for elem in elements:
            print(f"  - {elem.element_type}: {elem.content[:50]}...")