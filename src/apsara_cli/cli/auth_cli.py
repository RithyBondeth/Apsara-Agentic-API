import getpass
import httpx
from apsara_cli.shared.ui import ConsoleUI
from apsara_cli.cli.auth import save_auth_token, clear_auth_token, is_authenticated
from apsara_cli.config.defaults import settings

async def login() -> int:
    ui = ConsoleUI(use_color=True, auto_approve=True)
    
    ui.print_line()
    ui.info("Apsara Authentication Flow")
    
    if is_authenticated():
        ui.warning("You are already authenticated.")
        ui.print_line("Logging in again will overwrite your current token.")
        ui.print_line()
        ui.print_line(f"  {ui.badge('↵  continue', '17', '48;2;80;170;140')}  {ui.badge('n  cancel', '17', '48;2;200;100;80')}")
        choice = ui.read_single_key()
        if choice not in {"y", "Y", "\r", "\n", ""}:
            ui.info("Login cancelled.")
            return 0

    ui.print_line("Please enter your Apsara Access Token.")
    ui.print_line(ui.dim("You can find your token in your Apsara dashboard settings."))
    
    try:
        token = getpass.getpass("  Access Token: ").strip()
    except (EOFError, KeyboardInterrupt):
        ui.print_line()
        ui.error("Login aborted.")
        return 1

    if not token:
        ui.error("Access token cannot be empty.")
        return 1

    # Verify the token against the backend
    ui.status("Verifying token with Apsara...")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.APSARA_BASE_URL}/api/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if response.status_code == 200:
                user_data = response.json()
                ui.success(f"Successfully authenticated as {user_data.get('full_name', 'User')}!")
                save_auth_token(token)
                ui.info("Your token is stored securely in ~/.apsara/credentials.json")
                return 0
            else:
                error_detail = response.json().get("detail", "Unknown error")
                ui.error(f"Authentication failed: {error_detail}")
                return 1
    except httpx.ConnectError:
        ui.error(f"Could not connect to Apsara backend at {settings.APSARA_BASE_URL}")
        ui.info("Make sure the server is running.")
        return 1
    except Exception as e:
        ui.error(f"An unexpected error occurred during verification: {e}")
        return 1

def logout() -> int:
    ui = ConsoleUI(use_color=True, auto_approve=True)
    clear_auth_token()
    ui.success("Logged out successfully. Local credentials cleared.")
    return 0
