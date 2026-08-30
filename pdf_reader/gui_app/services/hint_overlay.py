"""
Hint Overlay - Vimium-style keyboard hints for PDF content
"""
from PyQt6.QtWidgets import QLabel, QWidget
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QFont


class HintMarker(QLabel):
    """
    Vimium-style hint marker
    - Fixed position on page
    - Shows hint character
    - Handles selection
    """
    
    def __init__(self, hint_text, element, parent=None):
        super().__init__(hint_text, parent)
        self.element = element
        
        # Style
        self.setStyleSheet("""
            QLabel {
                background-color: #e74c3c;
                color: white;
                font-weight: bold;
                font-size: 11px;
                padding: 2px 5px;
                border: 1px solid #c0392b;
                border-radius: 3px;
            }
        """)
        
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(28, 18)
        self.raise_()
    
    def get_element(self):
        """Get associated element"""
        return self.element


class HintOverlay:
    """
    Manages hint generation and display
    - Generates hints for visible pages
    - Handles element detection
    - Manages marker positioning
    """
    
    def __init__(self, scroll_area):
        self.scroll_area = scroll_area
        self.markers = []
        self.elements = []
        self.hint_chars = "asdfghjklqwertyuiopzxcvbnm"
    
    def generate_hints(self, doc, page_labels, current_zoom, visible_pages, mode="all"):
        """Generate hints for content on visible pages"""
        self.clear_markers()
        self.elements = []
        
        if not doc or not page_labels:
            return []
        
        # Get elements from visible pages
        all_elements = []
        for page_num in visible_pages:
            try:
                page = doc[page_num]
                
                # Use your existing ElementDetector
                from .element_detector import ElementDetector
                detector = ElementDetector(page, page_num)
                elements = detector.get_all_elements()
                
                # Filter by mode
                if mode == "text":
                    elements = [e for e in elements if getattr(e, 'type', None) == 'text']
                elif mode == "images":
                    elements = [e for e in elements if getattr(e, 'type', None) == 'image']
                
                all_elements.extend(elements)
            except Exception as e:
                print(f"Hint error on page {page_num}: {e}")
        
        if not all_elements:
            return []
        
        # Assign hints
        from .hint_generator import HintGenerator
        hint_gen = HintGenerator()
        all_elements = hint_gen.assign_hints(all_elements)
        self.elements = all_elements
        
        # Create markers
        for element in all_elements:
            # Get hint
            hint_text = getattr(element, 'hint', None) or str(element)
            if not hint_text or len(hint_text) > 3:
                continue
            
            # Get bbox
            rect = getattr(element, 'bbox', None)
            if not rect:
                continue
            
            # Get page number
            page_num = getattr(element, 'page', 0)
            if page_num >= len(page_labels):
                continue
            
            # Calculate position
            page_label = page_labels[page_num]
            page_pos = page_label.pos()
            
            x = page_pos.x() + int(rect[0] * current_zoom)
            y = page_pos.y() + int(rect[1] * current_zoom)
            
            # Create marker
            marker = HintMarker(hint_text, element, self.scroll_area.viewport())
            marker.move(x, y)
            marker.show()
            self.markers.append(marker)
        
        return self.markers
    
    def clear_markers(self):
        """Remove all hint markers"""
        for marker in self.markers:
            marker.hide()
            marker.deleteLater()
        self.markers = []
    
    def get_element_by_hint(self, hint_char):
        """Get element by hint character"""
        for element in self.elements:
            elem_hint = getattr(element, 'hint', None)
            if elem_hint and elem_hint.lower() == hint_char.lower():
                return element
        return None