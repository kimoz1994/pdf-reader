"""
PDF Search Engine - Background search for snappy performance
"""
from PyQt6.QtCore import QObject, pyqtSignal, QThread
import fitz


class SearchWorker(QThread):
    """Background worker for PDF search"""
    search_complete = pyqtSignal(list)  # Emits list of (page_num, rect) matches
    
    def __init__(self, doc, search_text):
        super().__init__()
        self.doc = doc
        self.search_text = search_text
    
    def run(self):
        """Search in background thread"""
        results = []
        
        try:
            for page_num in range(len(self.doc)):
                page = self.doc[page_num]
                text_instances = page.search_for(self.search_text)
                
                for inst in text_instances:
                    results.append((page_num, inst))
        except Exception as e:
            print(f"Search error: {e}")
        
        self.search_complete.emit(results)


class SearchEngine(QObject):
    """
    Manages PDF search with background threading
    - Non-blocking search
    - Tracks current results
    - Navigate between matches
    """
    
    search_started = pyqtSignal()
    search_results_ready = pyqtSignal(list)
    
    def __init__(self):
        super().__init__()
        self.current_worker = None
        self.results = []
        self.current_index = 0
    
    def search(self, doc, search_text):
        """Start background search"""
        if not doc or not search_text:
            return
        
        # Cancel previous search
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.terminate()
        
        # Start new search
        self.current_worker = SearchWorker(doc, search_text)
        self.current_worker.search_complete.connect(self._on_search_complete)
        self.current_worker.start()
        
        self.search_started.emit()
    
    def _on_search_complete(self, results):
        """Handle search completion"""
        self.results = results
        self.current_index = 0
        self.search_results_ready.emit(results)
    
    def next_result(self):
        """Get next search result"""
        if not self.results:
            return None
        
        self.current_index = (self.current_index + 1) % len(self.results)
        return self.results[self.current_index]
    
    def prev_result(self):
        """Get previous search result"""
        if not self.results:
            return None
        
        self.current_index = (self.current_index - 1) % len(self.results)
        return self.results[self.current_index]
    
    def get_current_result(self):
        """Get current result"""
        if not self.results:
            return None
        return self.results[self.current_index]
    
    def clear(self):
        """Clear search results"""
        self.results = []
        self.current_index = 0