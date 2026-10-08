import sys
import time
import threading
import ctypes
import serial
import serial.tools.list_ports
import flet as ft

try:
    import dxcam
    DXCAM_AVAILABLE = True
except ImportError:
    DXCAM_AVAILABLE = False

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

class SynapseAmbilightApp:
    def __init__(self):
        # Donanım ve Çalışma Değişkenleri
        self.is_running = False
        self.current_mode = "Ambilight_Block" 
        self.serial_connection = None
        self.thread = None
        self.brightness = 1.0
        self.camera = None
        
        self.NUM_LEDS_LEFT = 17
        self.NUM_LEDS_TOP = 31
        self.NUM_LEDS_RIGHT = 17
        self.TOTAL_LEDS = self.NUM_LEDS_LEFT + self.NUM_LEDS_TOP + self.NUM_LEDS_RIGHT
        self.HARDWARE_MAX_LEDS = 255 
        self.smoothing_factor = 0.25  
        self.prev_colors = [0] * (self.TOTAL_LEDS * 3)
        self.rainbow_hue = 0
        self.breathing_hue = 0

    def main(self, page: ft.Page):
        self.page = page
        page.title = "LIGHT UP ENGINE - v1.0"
        page.window_width = 800
        page.window_height = 680
        page.window_resizable = False
        page.padding = 30
        
        # --- GRADIENT ARKA PLAN ---
        page.theme_mode = ft.ThemeMode.DARK
        page.bgcolor = "transparent"
        page.decoration = ft.BoxDecoration(
            gradient=ft.LinearGradient(
                begin=ft.Alignment(1, 1),      
                end=ft.Alignment(-1, -1),    
                colors=["#050508", "#240608"] 
            )
        )

        
        self.mode_radio_group = ft.RadioGroup(
            content=ft.Column([
                ft.Radio(value="Ambilight_Block", label="Geniş Alan Blok Ortalama (Sinematik)", active_color="#ff2a3b"),
                ft.Radio(value="Rainbow", label="Gökkuşağı Akıcı Efekt (Rainbow)", active_color="#ff2a3b"),
                ft.Radio(value="Breathing", label="Yumuşak Renk Geçişi (Breathing)", active_color="#ff2a3b"),
                ft.Radio(value="Static", label="Sabit Renk Modu (Static)", active_color="#ff2a3b")
            ]),
            value="Ambilight_Block",
            on_change=self.change_mode
        )

       
        def color_selected(color_event):
            hex_color = color_event.control.bgcolor
            self.preview_circle.bgcolor = hex_color
            self.page.update()
            self.send_static_color(hex_color)

        # Geniş detaylı renk listesi
        detailed_colors = [
            "#ff0000", "#ff3333", "#ff6666", "#cc0000", "#990000",  # Kırmızılar
            "#00ff00", "#33ff33", "#66ff66", "#00cc00", "#009900",  # Yeşiller
            "#0000ff", "#3333ff", "#6666ff", "#0000cc", "#000099",  # Maviler
            "#ffff00", "#ffff33", "#ffff66", "#cccc00", "#999900",  # Sarılar
            "#00ffff", "#33ffff", "#ff00ff", "#ff33ff", "#ffffff",  # Cyan, Magenta, Beyaz
            "#ffaa00", "#ff5500", "#7700aa", "#aa0077", "#ff007f"   # Turuncu, Derin Mor ve Neon Pembe (Siyah yerine)
        ]

        # Pop-up pencere içeriğindeki grid yapısı
        picker_grid = ft.GridView(
            runs_count=5,
            max_extent=45,
            spacing=8,
            run_spacing=8,
            height=280,
            controls=[
                ft.Container(
                    bgcolor=c, 
                    border_radius=8, 
                    on_click=lambda e: [color_selected(e), self.close_color_picker()]
                )
                for c in detailed_colors
            ]
        )

        # Kapatma butonu olan diyalog penceresi
        self.color_dialog = ft.AlertDialog(
            title=ft.Text("Detaylı Renk Paleti", color="#ff2a3b", weight=ft.FontWeight.BOLD),
            content=picker_grid,
            actions=[
                ft.TextButton("Kapat", on_click=lambda _: self.close_color_picker())
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=lambda _: self.close_color_picker() # Boşluğa tıklayıp kapatınca da state'i temizle
        )

        # Renk Önizleme Çemberi
        self.preview_circle = ft.Container(
            width=30, height=30, 
            border_radius=15, 
            border=ft.Border(
                top=ft.BorderSide(2, "#ff2a3b"),
                bottom=ft.BorderSide(2, "#ff2a3b"),
                left=ft.BorderSide(2, "#ff2a3b"),
                right=ft.BorderSide(2, "#ff2a3b")
            ),
            bgcolor="#1a1a24"
        )

        # UI Başlıkları
        title = ft.Text("LIGHT UP Control Center", size=24, weight=ft.FontWeight.BOLD, color="#ff2a3b")
        subtitle = ft.Text("MULTIPLE DEVICE MANAGEMENT PANEL", size=11, color="#6b7280")

        # Kombo Kutu (Port Seçimi)
        self.port_dropdown = ft.Dropdown(
            width=220,
            label="COM Port Seçin",
            border_color="#27273a",
            focused_border_color="#ff2a3b",
            color="white",
        )

        # Switch ve Slider
        self.system_switch = ft.Switch(
            label="Ambilight Aktif", 
            active_color="#ff2a3b",
            on_change=self.toggle_system
        )
        
        self.bright_slider = ft.Slider(
            min=0.1, max=1.0, divisions=9, 
            value=1.0, active_color="#ff2a3b",
            on_change=self.update_brightness
        )

        self.status_text = ft.Text("Durum: Cihaz Bağlantısı Bekleniyor", italic=True, color="#fbbf24")

        # --- MODERN KARTLARIN OLUŞTURULMASI ---
        left_card = ft.Container(
            content=ft.Column([
                ft.Text("Sistem ve Bağlantı", size=16, weight=ft.FontWeight.BOLD),
                ft.Divider(color="#27273a"),
                self.system_switch,
                ft.Text("Donanım Bağlantısı", size=12, color="#6b7280"),
                ft.Row([
                    self.port_dropdown,
                    ft.IconButton(ft.Icons.AUTORENEW, icon_color="#ff2a3b", on_click=lambda _: self.refresh_ports())
                ]),
                ft.Text("Parlaklık Seviyesi", size=14, weight=ft.FontWeight.BOLD),
                self.bright_slider,
            ], spacing=15),
            padding=20,
            border_radius=15,
            bgcolor="#121622",
            border=ft.Border(
                top=ft.BorderSide(1, "#1e293b"), bottom=ft.BorderSide(1, "#1e293b"),
                left=ft.BorderSide(1, "#1e293b"), right=ft.BorderSide(1, "#1e293b")
            )
        )

        # Yeni Flet Button API'sine göre güncellenmiş buton yapısı
        modern_picker_btn = ft.Button(
            content=ft.Row(
                [ft.Icon(ft.Icons.COLOR_LENS, color="white"), ft.Text("Renk Seçim Penceresini Aç", color="white")],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=5
            ),
            style=ft.ButtonStyle(
                bgcolor="#ff2a3b",
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
            on_click=lambda _: self.open_color_picker()
        )

        right_card = ft.Container(
            content=ft.Column([
                ft.Text("Işık ve Efekt Modları", size=16, weight=ft.FontWeight.BOLD),
                ft.Divider(color="#27273a"),
                self.mode_radio_group,  
                
                ft.Divider(color="#27273a"), 
                ft.Text("Özel Renk Seçimi", size=14, weight=ft.FontWeight.BOLD),
                ft.Row([
                    modern_picker_btn,
                    ft.Row([
                        ft.Text("Aktif:", size=12, color="#6b7280"),
                        self.preview_circle
                    ], spacing=5)
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            ], spacing=15),
            padding=20,
            border_radius=15,
            bgcolor="#121622",
            expand=True,
            border=ft.Border(
                top=ft.BorderSide(1, "#1e293b"), bottom=ft.BorderSide(1, "#1e293b"),
                left=ft.BorderSide(1, "#1e293b"), right=ft.BorderSide(1, "#1e293b")
            )
        )

        # Sayfa Düzeni Düzenleme
        page.add(
            ft.Column([
                title,
                subtitle,
                ft.Row([
                    ft.Column([left_card, self.status_text], width=340),
                    right_card
                ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.START, expand=True)
            ], spacing=10)
        )
        
        # Dialogu başlangıçta overlay'e ekliyoruz ki her seferinde append etmekle uğraşmayalım
        page.overlay.append(self.color_dialog)
        self.refresh_ports()

    # --- PENCERE TETİKLEYİCİLERİ ---
    def open_color_picker(self):
        self.color_dialog.open = True
        self.page.update()

    def close_color_picker(self):
        self.color_dialog.open = False
        self.page.update()

    # --- AYGIT VE ARKA PLAN FONKSİYONLARI ---
    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        if ports:
            self.port_dropdown.options = [ft.dropdown.Option(p) for p in ports]
            self.port_dropdown.value = ports[0]
        else:
            self.port_dropdown.options = [ft.dropdown.Option("Cihaz Bulunamadı")]
            self.port_dropdown.value = "Cihaz Bulunamadı"
        self.page.update()

    def change_mode(self, e):
        self.current_mode = self.mode_radio_group.value
        self.page.update()

    def update_brightness(self, e):
        self.brightness = float(self.bright_slider.value)

    def send_data_to_skydimo(self, led_bytes):
        if not self.serial_connection or not self.serial_connection.is_open: return
        try:
            count = self.HARDWARE_MAX_LEDS - 1
            hi = (count >> 8) & 0xFF
            lo = count & 0xFF
            chk = hi ^ lo ^ 0x55
            header = bytes([0x41, 0x64, 0x61, hi, lo, chk])
            payload = list(led_bytes[:self.TOTAL_LEDS * 3])
            needed_bytes = (self.HARDWARE_MAX_LEDS * 3) - len(payload)
            if needed_bytes > 0:
                payload.extend([0] * needed_bytes)
            self.serial_connection.write(header + bytes(payload))
            self.serial_connection.flush()
        except: pass

    def toggle_system(self, e):
        if self.system_switch.value is True: 
            selected_port = self.port_dropdown.value
            if selected_port == "Cihaz Bulunamadı" or not selected_port:
                self.status_text.value = "Hata: Geçersiz Port!"
                self.status_text.color = "ff2a3b"
                self.system_switch.value = False
                self.page.update()
                return
            try:
                if DXCAM_AVAILABLE:
                    if self.camera: del self.camera
                    self.camera = dxcam.create(output_color="RGB", max_buffer_len=2)
                    self.camera.start(target_fps=60, video_mode=True)
                
                self.serial_connection = serial.Serial(selected_port, 115200, timeout=0.01)
                time.sleep(0.5) 
                self.is_running = True
                self.status_text.value = "Sistem Aktif: Akış Sağlanıyor"
                self.status_text.color = "#3b82f6"
                self.page.update()
                
                self.prev_colors = [0] * (self.TOTAL_LEDS * 3)
                self.thread = threading.Thread(target=self.main_worker, daemon=True)
                self.thread.start()
            except Exception as ex:
                self.status_text.value = f"Bağlantı Hatası: {ex}"
                self.status_text.color = "red"
                self.system_switch.value = False
                self.page.update()
        else: 
            self.is_running = False
            time.sleep(0.1)
            if self.camera:
                self.camera.stop()
                self.camera = None
            if self.serial_connection and self.serial_connection.is_open:
                self.send_data_to_skydimo([0] * (self.TOTAL_LEDS * 3))
                self.serial_connection.close()
            self.status_text.value = "Sistem Durduruldu."
            self.status_text.color = "#fbbf24"
            self.page.update()

    def send_static_color(self, hex_color):
        if not self.is_running: return
        hex_color = hex_color.lstrip('#')
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        static_data = [int(r*self.brightness), int(g*self.brightness), int(b*self.brightness)] * self.TOTAL_LEDS
        self.prev_colors = static_data
        self.send_data_to_skydimo(static_data)

    def hsv_to_rgb(self, h, s, v):
        h = float(h) / 255.0; s = float(s) / 255.0; v = float(v) / 255.0
        if s == 0.0: return int(v*255), int(v*255), int(v*255)
        i = int(h*6.0); f = (h*6.0) - i
        p = v * (1.0 - s); q = v * (1.0 - s*f); t = v * (1.0 - s*(1.0-f))
        i %= 6
        if i == 0: return int(v*255), int(t*255), int(p*255)
        if i == 1: return int(q*255), int(v*255), int(p*255)
        if i == 2: return int(p*255), int(v*255), int(t*255)
        if i == 3: return int(p*255), int(q*255), int(v*255)
        if i == 4: return int(t*255), int(p*255), int(v*255)
        if i == 5: return int(v*255), int(p*255), int(p*255)

    def main_worker(self):
        block_thickness = 60 
        while self.is_running:
            t_start = time.time()
            if self.current_mode == "Ambilight_Block":
                try:
                    if self.camera:
                        frame = self.camera.get_latest_frame()
                        if frame is None: 
                            time.sleep(0.002)
                            continue
                        H, W, _ = frame.shape
                    else:
                        time.sleep(0.1)
                        continue
                    
                    new_colors = [0] * (self.TOTAL_LEDS * 3)
                    led_index = 0
                    
                    # SOL KENAR
                    seg_h_left = H / self.NUM_LEDS_LEFT
                    for i in reversed(range(self.NUM_LEDS_LEFT)):
                        y1 = int(i * seg_h_left)
                        y2 = int((i + 1) * seg_h_left)
                        block = frame[y1:y2, 0:block_thickness]
                        avg_color = cv2.resize(block, (1, 1))[0][0]
                        new_colors[led_index*3]     = int(avg_color[0] * self.brightness)
                        new_colors[led_index*3 + 1] = int(avg_color[1] * self.brightness)
                        new_colors[led_index*3 + 2] = int(avg_color[2] * self.brightness)
                        led_index += 1
                        
                    # ÜST KENAR
                    seg_w_top = W / self.NUM_LEDS_TOP
                    for i in range(self.NUM_LEDS_TOP):
                        x1 = int(i * seg_w_top)
                        x2 = int((i + 1) * seg_w_top)
                        block = frame[0:block_thickness, x1:x2]
                        avg_color = cv2.resize(block, (1, 1))[0][0]
                        new_colors[led_index*3]     = int(avg_color[0] * self.brightness)
                        new_colors[led_index*3 + 1] = int(avg_color[1] * self.brightness)
                        new_colors[led_index*3 + 2] = int(avg_color[2] * self.brightness)
                        led_index += 1
                        
                    # SAĞ KENAR
                    seg_h_right = H / self.NUM_LEDS_RIGHT
                    for i in range(self.NUM_LEDS_RIGHT):
                        y1 = int(i * seg_h_right)
                        y2 = int((i + 1) * seg_h_right)
                        block = frame[y1:y2, W - block_thickness:W]
                        avg_color = cv2.resize(block, (1, 1))[0][0]
                        new_colors[led_index*3]     = int(avg_color[0] * self.brightness)
                        new_colors[led_index*3 + 1] = int(avg_color[1] * self.brightness)
                        new_colors[led_index*3 + 2] = int(avg_color[2] * self.brightness)
                        led_index += 1
                    
                    smoothed_data = []
                    for i in range(self.TOTAL_LEDS * 3):
                        diff = new_colors[i] - self.prev_colors[i]
                        val = int(self.prev_colors[i] + (diff * self.smoothing_factor))
                        smoothed_data.append(max(0, min(val, 255)))
                        
                    self.send_data_to_skydimo(smoothed_data)
                    self.prev_colors = smoothed_data
                    
                    t_elapsed = time.time() - t_start
                    time.sleep(max(0.005, 0.0166 - t_elapsed))
                except Exception:
                    time.sleep(0.01)
                    
            elif self.current_mode == "Rainbow":
                led_data = []
                for i in range(self.TOTAL_LEDS):
                    hue_val = (self.rainbow_hue + (i * 3)) % 255
                    r, g, b = self.hsv_to_rgb(hue_val, 255, int(255 * self.brightness))
                    led_data.extend([r, g, b])
                self.send_data_to_skydimo(led_data)
                self.rainbow_hue = (self.rainbow_hue + 2) % 255
                time.sleep(0.02)
                
            elif self.current_mode == "Breathing":
                r, g, b = self.hsv_to_rgb(self.breathing_hue, 255, int(255 * self.brightness))
                led_data = [r, g, b] * self.TOTAL_LEDS
                self.send_data_to_skydimo(led_data)
                self.breathing_hue = (self.breathing_hue + 1) % 255
                time.sleep(0.03)
            else:
                time.sleep(0.05)

if __name__ == "__main__":
    app = SynapseAmbilightApp()
    ft.run(app.main)