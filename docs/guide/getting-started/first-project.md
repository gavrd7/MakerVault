# Your first project

**Goal:** practise the complete workflow with a small electronics enclosure project. Use sample records or substitute your own parts; do not enter pretend quantities into an existing real inventory.

## 1. Find the board

Open **Board Catalogue**, search for your board and open its details. Check the exact variant, operating voltage and available specifications. A blank value means unknown, not necessarily unsupported. If your variant is absent, an authorised editor can add a suitable catalogue record; avoid renaming a different board to make it fit.

## 2. Record what you own

Use the board's inventory action, or **Inventory → Add item**. Select the board, enter a quantity such as `2`, its actual condition and a location such as `Drawer A2`. Leave the identifier blank to use the generated ID. Save and reopen the inventory record to check it.

**Expected result:** one inventory row representing two physical boards, separate from the catalogue definition.

## 3. Create the build

Open **Projects → New project**. Name it `Desk sensor enclosure`, add a short description and save. Open the project and add a few build notes. You can add a cover image later.

## 4. Plan the parts

In the project's bill of materials, add a line for one of the boards. Set required quantity to `1`. Add other needed components or a custom item such as mounting screws.

Allocate `1` from your two-board inventory row to the matching BOM line. Check the line's coverage and the inventory's allocated/free quantities.

**Expected result:** total stock stays at two; one is reserved for this build and one remains unallocated. An allocation is a reservation, not a purchase or stock-consumption transaction.

## 5. Keep the files together

Use **＋ File** in the project to upload a wiring diagram or notes. Add your repository with **＋ Repository** if the firmware lives in GitHub or another Git host. The repository entry is a link; it does not clone, back up or synchronise the repository's contents.

When a file changes, use **Upload new version**. Open version history and confirm the earlier file is still available.

## 6. Add the printed enclosure when ready

In **3D Printing**, add a model, upload an STL/3MF and associate it with this project. Open the viewer and inspect the dimensions and printer fit. Prepare the actual print in your slicer. After printing, record the job, spool usage and result.

You now have a project that connects the plan, reserved physical parts, digital files and printed output. The remaining chapters explain each area in detail.
