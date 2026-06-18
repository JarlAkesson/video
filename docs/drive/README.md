# Google Drive

This directory documents what lives on Google Drive and how it is organized.
Binary files (PDFs, audio, images, video) are stored there rather than in git.

**Drive link:** _[add shared folder link here]_

---

## Why Drive and not git?

Git is designed for text files. Binary files like PDFs and audio bloat the
repository and make it slow for everyone. Drive handles large files well and
lets non-technical collaborators upload and download without knowing git.

---

## Folder structure

Drive does not need to follow a fixed structure. A good starting point is to
mirror what is under `assets/` in this repository:

```
assets/
├── lyrics/      Lyrics as plain text files
├── meta/        Spreadsheets and other reference documents
├── midi/        MIDI files
├── sheets/      Sheet music in PDF or image format
└── xml/         MusicXML files
```

If Drive uses a different structure that is fine, but **each folder on Drive
must contain a README file** (a Google Doc or a plain text file called README)
explaining what is in that folder. This makes it possible for anyone to
understand what they are looking at and to map Drive files into the right
place under `assets/` locally.

---

## Working locally

When you need to work with Drive files in the pipeline scripts, download them
into the corresponding folder under `assets/` in this repository. That folder
is gitignored, so your local copies will not be committed to git by accident.
