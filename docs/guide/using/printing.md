# Printers, filament and spools

**Goal:** describe your equipment and materials, then record the physical things you own.

| Record | Meaning |
| --- | --- |
| Printer model | Shared specifications for a machine type |
| Owned printer | Your particular machine, with name, location and connection details |
| Filament product | A material/product/colour definition |
| Physical spool | One actual reel with its own weight, price and identity |
| Slot | A position in a printer's multi-material system |

## Add your printer

1. Open **3D Printing** and choose the add-printer action.
2. In **Add owned printer**, select the manufacturer and model. Use the custom-model option when necessary.
3. Give the machine a recognisable name and location.
4. Review its specifications and save.
5. Use **Manage printer** to correct details later.

A printer model may support a multi-material system without your particular machine having one installed. Record the installed hardware accurately. Add a local host/IP only if an integration needs it; a normal manual printer record does not require a network connection.

Printer catalogue names may come from OrcaSlicer profiles. A catalogue entry is not proof of a working live integration or complete build-volume data.

## Add filament, then add a spool

1. Open the filament area and choose **Add filament product** or the open catalogue browser.
2. Search/choose the product or enter a custom manufacturer, material and colour. Review appearance and other details, then save/import.
3. Return to physical spools and choose **Add physical spool**.
4. Select the filament product, enter initial and remaining filament weight, purchase cost/currency and status as appropriate.
5. Choose a storage location, printer assignment or leave it unassigned. Save.

Spool IDs are generated automatically. Two identical reels should be two spool records when you need to track them separately. Colour, manufacturer and material do not uniquely identify a reel. RFID/UID can identify a specific physical spool where available.

Weight fields refer to filament amounts; do not put the combined plastic-reel-and-filament scale reading into a filament-only remaining-weight field without accounting for the empty spool.

### Filament catalogue data and images

Imported SpoolmanDB products retain their catalogue identity and provenance while becoming normal editable MakerVault filament products. Catalogue maintenance can refresh **missing** density, weight, colour/appearance and print-temperature data without replacing values you have corrected manually. Where the upstream record provides them, MakerVault also retains manufacturer product, technical-data and safety-data links plus spool/refill metadata.

Filament images follow the same conservative policy as the other MakerVault catalogues. An authoritative manufacturer product page can provide a remote image reference; confidently matched openly licensed media may be cached locally. MakerVault does not copy arbitrary commercial product imagery merely because it appears in search results. Editors can also use **Image** in the Filament Library to upload their own product image; administrators may provide a safe public HTTPS image URL.

**Settings → Library updates** includes filament data in the normal catalogue-maintenance schedule and reports filament coverage for images, manufacturers, colour data, density, nominal weight, print temperatures and source links.

## Locations and slots

Create reusable printing locations such as a room, shelf or dry box. Update the placement when moving a spool. A discovered slot may display a material and colour before it has a physical spool linked.

Use **Add to inventory** / **Identify detected physical spool** to choose whether the detected reel is an existing unloaded spool or a genuinely new one. Confirm the physical identity before linking it.

## Optional connections

Live monitoring is implemented for Creality, Moonraker/Klipper, OctoPrint, Bambu Lab local, PrusaLink, Anycubic LAN and FlashForge local. Compatible Elegoo, QIDI, Sovol, Snapmaker U1 and Voron profiles reuse Moonraker. Spoolman, Creality CFS and SimplyPrint provide complementary inventory/service integrations. Most manufacturer hardware remains experimental pending testing; these are implemented adapters, not blanket promises for every model.

K1/K2 monitoring and camera playback have owner confirmation. Add a live source through **Live monitor**; the optional second step offers camera setup. Later, use the separate **Camera setup** printer action. Visible printer/dashboard cards automatically show the last configured enabled camera, with a Fullscreen control and no setup selectors. [Camera instructions](../integrations/printer-cameras.md) explain the transport limits.

Pause, Resume and confirmed Cancel are optional per-source controls for Creality, Moonraker and OctoPrint. Hardware control validation remains separate. See [controls](../integrations/printer-controls.md) and [adapter validation](../integrations/printer-adapter-validation.md).

[Printed parts](printed-parts.md) are created explicitly. Filament tracking does not require saving a model or retaining a part.

[Spoolman setup →](../integrations/spoolman.md) · [Creality CFS →](../integrations/creality.md) · [SimplyPrint →](../integrations/simplyprint.md)
