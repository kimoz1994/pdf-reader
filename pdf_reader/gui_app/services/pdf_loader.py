"""
This module loads a pdf file and extracts basic info.

key concepts:
- pymupdf represents pdfs as 'document' objects
- each page can be accessed like a list: doc[0], doc[1], etc.
- pages have text, images, and other elements that can be extracted


"""

import fitz  # PyMuPDF

class PDFLoader:
    """load and inspect a pdf file"""

    def __init__(self, pdf_path:str):
        """initialize by openining the pdf.

        Args:
            pdf_path (str): path to the pdf file
        """

        self.doc = fitz.open(pdf_path)
        self.pdf_path = pdf_path

    def get_info(self)->dict:

        """get basic infor about a pdf"""

        return{

            'path': self.pdf_path,
            'num_pages': len(self.doc),
            'metadata': self.doc.metadata,
        }

    def get_page(self, page_num:int):
        """ 

        get a specific pages from the pdf.

        args:
        page_num: page number (0-indexed)

        returns:
        page object
        """
        if page_num < 0 or page_num >= len(self.doc):
            raise ValueError(f"Page number {page_num} is out of range. The document has {len(self.doc)} pages.") 

        return self.doc[page_num]

    def close(self):
        """close the pdf file (important for cleanup)"""

        self.doc.close()
    
    def __enter__(self):
        """context manager entry(for 'with' statement)"""
        return self

    def __exit__(self, exc_type,exc_val,exc_tb):
        """context manager exit(automatically calls close())"""
        self.close()


    
# test code

if __name__ == "__main__":

    # example usage

    with PDFLoader("sample.pdf") as loader:
        info = loader.get_info()
        print(f"pdf: {info['path']}")
        print(f"pages: {info['num_pages'] }")




