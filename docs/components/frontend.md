# Frontend Component

The **Frontend** component provides the user interface and handles user interactions for your Aegis Stack application.

## Current Implementation: Flet

Flet is the current frontend implementation, chosen for its Python-native approach and ability to create both web and desktop applications from the same codebase.

### Why Flet?

- **Pure Python**: Write UI logic in Python without JavaScript/HTML/CSS
- **Multi-Platform**: Same code runs as web app, desktop app, or mobile app
- **Fast Development**: No context switching between languages
- **Modern UI**: Based on Flutter, providing smooth animations and responsive design
- **Real-time**: Built-in WebSocket support for live updates

### How It's Integrated

Flet is set up in the `app/frontend/` directory and integrated with FastAPI:

```python
# app/frontend/main.py
import flet as ft

def create_frontend_app():
    """Create and return Flet session handler"""
    
    async def main(page: ft.Page):
        page.title = "Aegis Stack"
        page.theme_mode = ft.ThemeMode.LIGHT
        
        # Your UI components here
        page.add(
            ft.Text("Welcome to Aegis Stack!", size=24),
            ft.ElevatedButton("Click me!", on_click=handle_click)
        )
    
    return main

async def handle_click(e):
    e.page.add(ft.Text("Button clicked!"))
    e.page.update()
```

### Integration with FastAPI

Flet mounts seamlessly on FastAPI using the official integration:

```python
# app/integrations/main.py
import flet.fastapi as flet_fastapi

# Create and mount the Flet app
session_handler = create_frontend_app()
flet_app = flet_fastapi.app(session_handler)
app.mount("/", flet_app)
```

### Key Features

#### Component-Based Architecture
```python
# Reusable components
class CustomButton(ft.UserControl):
    def __init__(self, text, on_click):
        super().__init__()
        self.text = text
        self.on_click = on_click
    
    def build(self):
        return ft.ElevatedButton(
            text=self.text,
            on_click=self.on_click
        )
```

#### State Management
```python
# Reactive state updates
async def update_counter(e):
    counter.value += 1
    counter.update()  # Automatically syncs with browser
```

#### Responsive Design
```python
# Adaptive layouts
ft.ResponsiveRow([
    ft.Container(
        content=ft.Text("Left panel"),
        col={"sm": 6, "md": 4, "xl": 3}
    ),
    ft.Container(
        content=ft.Text("Right panel"), 
        col={"sm": 6, "md": 8, "xl": 9}
    )
])
```

### Development Experience

- **Hot Reload**: Changes appear instantly during development
- **Python Debugging**: Use standard Python debuggers and tools
- **Type Safety**: Full type hints and IDE support
- **No Build Step**: No compilation or bundling required

### Integration with Aegis Stack

Flet integrates seamlessly with Aegis Stack's architecture:

- **Lifecycle Management**: Automatic startup and shutdown handling
- **Structured Logging**: Integrated with Aegis Stack's logging system
- **Async Compatibility**: Works with FastAPI's async request handling


## Performance Characteristics

Flet provides:

- **Real-time Updates**: WebSocket-based communication with server
- **Efficient Rendering**: Flutter's optimized rendering engine
- **Small Bundle Size**: No heavy JavaScript frameworks
- **Cross-Platform**: Same performance characteristics across platforms

## Deployment Options

Flet applications can be deployed as:

- **Web App**: Served through FastAPI (current setup)
- **Desktop App**: Standalone executable for Windows/Mac/Linux
- **Mobile App**: Native iOS/Android applications
- **PWA**: Progressive Web App with offline capabilities

This makes Flet an ideal choice for Aegis Stack's Python-first, async-native philosophy.