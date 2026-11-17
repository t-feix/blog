Static Blog generator

1. How to run locally on localhost:800

   ```bash
   pip install -r requirements.txt
   python build.py serve
   ```

2. how to write

   add file to `posts/`, e.g. `posts/2026-11-17-blah.md`:

   ```markdown
   ---
   title: blah blah blah
   tags: blah, bluh
   description: description
   draft: false
   ---

   ...
   ```

3. files in `pages/` become standalone pages such as `pages/blah.md` -> `/blah/`.

4. images and other assets go in `static/` and are linked as `/static/whatever.png`.