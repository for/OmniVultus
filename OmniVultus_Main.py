import os, sys, logging, asyncio, aiohttp, pytesseract
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtWidgets import *
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PIL import ImageGrab

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', filename='browser.log')

class ApiWorker(QThread):
    finished = pyqtSignal(str)
    def __init__(self, system_message, content, temperature, max_tokens):
        super().__init__()
        self.system_message, self.content = system_message, content
        self.temperature, self.max_tokens = temperature, max_tokens

    async def fetch_api(self):
        api_url = "http://127.0.0.1:1234/v1/chat/completions"
        headers = {"Content-Type": "application/json", "Authorization": "Bearer YOUR_API_KEY"} # Dosn't need to be set for LMStudio
        payload = {"messages": [{"role": "system", "content": self.system_message}, {"role": "user", "content": self.content}], "temperature": self.temperature, "max_tokens": self.max_tokens}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    api_response = await response.json()
                    role, content, usage = api_response['choices'][0]['message']['role'], api_response['choices'][0]['message']['content'], api_response['usage']
                    return f"Role: {role}\nContent: {content}\nUsage: {usage}"
        except Exception as e:
            logging.error(f"API request failed: {e}")
            return f"API request failed: {e}"

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(self.fetch_api())
        self.finished.emit(result)

class ScreenCaptureWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.start_pos = None
        self.end_pos = None
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0.3);")

    def mousePressEvent(self, event):
        self.start_pos = event.pos()
        self.end_pos = None
        self.update()

    def mouseMoveEvent(self, event):
        self.end_pos = event.pos()
        self.update()

    def mouseReleaseEvent(self, event):
        self.end_pos = event.pos()
        self.capture_region()
        self.close()

    def paintEvent(self, event):
        if self.start_pos and self.end_pos:
            painter = QPainter(self)
            painter.setPen(QPen(Qt.GlobalColor.red, 2, Qt.PenStyle.SolidLine))
            painter.drawRect(QRect(self.start_pos, self.end_pos))

    def capture_region(self):
        if self.start_pos and self.end_pos:
            web_browser = self.parent().browser # Get the web browser widget
            x1 = min(self.start_pos.x(), self.end_pos.x()) # Calculate the selected region
            y1 = min(self.start_pos.y(), self.end_pos.y())
            width = abs(self.start_pos.x() - self.end_pos.x())
            height = abs(self.start_pos.y() - self.end_pos.y())
            x1 -= web_browser.pos().x() # Adjust the coordinates to be relative to the web page
            y1 -= web_browser.pos().y()
            screenshot = web_browser.grab() # Render the contents of the web browser widget to a QPixmap
            region = screenshot.copy(x1, y1, width, height) # Extract the region from the screenshot
            region.save("screenshot.png", "png") # Save the region
            print(f"Screenshot Saved: Region at ({x1}, {y1}) with width {width} and height {height}")
            self.extract_text_from_image("screenshot.png") # Extract text from the saved image

    def extract_text_from_image(self, image_path):
        try:
            text = pytesseract.image_to_string(image_path) # Use pytesseract to extract text from the image
            print(f"Extracted Text: {text}")
            self.parent().handle_ocr_text(text)
        except Exception as e: logging.error(f"OCR failed: {e}")

class WebBrowser(QMainWindow):
    def __init__(self):
        super().__init__()
        self.browser = QWebEngineView()
        self.url_bar = QLineEdit()
        self.url_bar.returnPressed.connect(lambda: self.navigate_to_url(self.url_bar.text()))
        navbar = QToolBar() # NavBar
        self.addToolBar(navbar)
        navbar.addWidget(self.url_bar)
        actions = [("Back", self.browser.back), ("Forward", self.browser.forward), ("Reload", self.browser.reload), ("Home", lambda: self.navigate_to_url("https://www.google.com"))]
        for label, method in actions:
            action = QAction(label, self)
            action.triggered.connect(method)
            navbar.addAction(action)
        options_menu = QMenu("Options", self)
        dark_mode_action = QAction("Toggle Dark Mode", self)
        dark_mode_action.triggered.connect(self.toggle_dark_mode)
        options_menu.addAction(dark_mode_action) # Options Menu
        options_button = QToolButton()
        options_button.setText("Options")
        options_button.setMenu(options_menu)
        options_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        navbar.addWidget(options_button)
        api_widget = QWidget() # Api Widget
        api_layout = QVBoxLayout()
        self.system_message_dropdown = QComboBox()
        self.system_message_dropdown.addItems([
            "Explain the text in a professional manner.", "Summarize the content briefly.",
            "Extract key points from the text.", "Identify any deals or offers mentioned.",
            "Find the lowest priced deal or offer and show the details of that.", 
            "Find and list all email adresses in the text.", "Find and list all the hyperlinks in the text, list the hyperlink name and url."
        ])
        api_layout.addWidget(self.system_message_dropdown)
        self.system_message_input = QLineEdit()
        self.system_message_input.setPlaceholderText("Or enter a custom system message here...")
        api_layout.addWidget(self.system_message_input)
        self.send_button = QPushButton("Send to API")
        self.send_button.clicked.connect(self.send_to_api)
        self.ocr_button = QPushButton("Capture Screen Region")
        self.ocr_button.clicked.connect(self.capture_screen_region)
        self.results_output = QTextEdit(readOnly=True)
        api_layout.addWidget(self.send_button)
        api_layout.addWidget(self.ocr_button)
        api_layout.addWidget(self.results_output)
        
        self.loading_label = QLabel()
        script_dir = os.path.dirname(os.path.abspath(__file__))
        loading_gif_path = os.path.join(script_dir, "loading.gif")
        self.loading_movie = QMovie(loading_gif_path)
        self.loading_label.setMovie(self.loading_movie)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setFixedSize(300, 150)
        api_layout.addWidget(self.loading_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self.loading_label.hide()
        spin_boxes = [("Temperature:", QDoubleSpinBox(), 0.0, 1.0, 0.1, 0.2), ("Max Tokens:", QSpinBox(), 1, 130000, 1, 16000)]
        for label_text, spin_box, min_val, max_val, step, default in spin_boxes:
            layout = QHBoxLayout(); label = QLabel(label_text)
            spin_box.setRange(min_val, max_val); spin_box.setSingleStep(step); spin_box.setValue(default)
            layout.addWidget(label); layout.addWidget(spin_box)
            api_layout.addLayout(layout)
            if label_text == "Temperature:": self.temperature_input = spin_box
            else: self.max_tokens_input = spin_box

        api_widget.setLayout(api_layout)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.browser)
        splitter.addWidget(api_widget)
        self.setCentralWidget(splitter)
        self.browser.urlChanged.connect(lambda q: self.url_bar.setText(q.toString()))
        self.navigate_to_url("https://www.example.com")
        self.setWindowTitle("Omni Browser")
        self.resize(1200, 800)

    def navigate_to_url(self, url):
        if not url.startswith(('http://', 'https://')): url = f'https://{url}'
        self.url_bar.setText(url)
        self.browser.setUrl(QUrl(url))
        self.setWindowTitle(f"Browser - {url}")

    def send_to_api(self): self.browser.page().toPlainText(self.handle_webpage_content)
    
    def handle_webpage_content(self, content):
        custom_message = self.system_message_input.text()
        system_message = custom_message if custom_message else self.system_message_dropdown.currentText()
        temperature, max_tokens = self.temperature_input.value(), self.max_tokens_input.value()
        self.api_worker = ApiWorker(system_message, content, temperature, max_tokens)
        self.api_worker.finished.connect(self.display_api_result)
        self.api_worker.start()
        self.loading_label.show()
        self.loading_movie.start()

    def display_api_result(self, result):
        self.results_output.setPlainText(result)
        self.loading_movie.stop()
        self.loading_label.hide()

    def toggle_dark_mode(self):
        dark_mode_css = """body {background-color:#233550; color:#ffffff;} h1 {color: #5F9089;} a {color: #5F9089;} p {color: #5F9064;}"""
        self.browser.page().runJavaScript(f"""(function() {{var style=document.createElement('style'); style.innerHTML=`{dark_mode_css}`; document.head.appendChild(style);}})();""")

    def capture_screen_region(self):
        self.screen_capture_widget = ScreenCaptureWidget()
        self.screen_capture_widget.setParent(self)
        self.screen_capture_widget.show()

    def handle_ocr_text(self, text):
        custom_message = self.system_message_input.text() # Use the extracted text from the OCR instead of the full page content
        system_message = custom_message if custom_message else self.system_message_dropdown.currentText()
        temperature, max_tokens = self.temperature_input.value(), self.max_tokens_input.value()
        self.api_worker = ApiWorker(system_message, text, temperature, max_tokens)
        self.api_worker.finished.connect(self.display_api_result)
        self.api_worker.start()
        self.loading_label.show()
        self.loading_movie.start()

def main():
    app = QApplication(sys.argv)
    browser = WebBrowser()
    browser.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()