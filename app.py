
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

import gradio as gr
import glob
import sqlite3
import cv2
import datetime
import pandas as pd
import base64
import urllib.parse
from fastapi import FastAPI
from fastapi.responses import FileResponse
from videotofaces import video_to_faces

DB_FILE = "faces_db.sqlite"

app = FastAPI()

@app.get("/files/{path:path}")
async def read_file(path: str):
    return FileResponse(path)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fps REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER,
            frame_number INTEGER,
            timestamp_seconds REAL,
            face_image_path TEXT,
            person_name TEXT,
            cluster_id INTEGER,
            FOREIGN KEY(video_id) REFERENCES videos(id)
        )
    ''')
    conn.commit()
    conn.close()

def get_all_data():
    conn = sqlite3.connect(DB_FILE)
    query = """
        SELECT
            f.id AS face_id,
            f.face_image_path,
            v.filename AS video_filename,
            v.filepath AS video_filepath,
            f.timestamp_seconds,
            COALESCE(f.person_name, 'Cluster ' || f.cluster_id) AS name,
            v.upload_date
        FROM faces f
        JOIN videos v ON f.video_id = v.id
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def format_timestamp(seconds):
    if seconds is None:
        return "00:00"
    minutes = int(seconds // 60)
    seconds = int(seconds % 60)
    return f"{minutes:02d}:{seconds:02d}"

def create_gallery_html(df, cols):
    if df.empty:
        return ""
    html = f"<div style='display: grid; grid-template-columns: repeat({cols}, 1fr); gap: 10px;'>"
    for _, row in df.iterrows():
        try:
            with open(row['face_image_path'], 'rb') as img_file:
                encoded_string = base64.b64encode(img_file.read()).decode('utf-8')
            image_data = f"data:image/jpeg;base64,{encoded_string}"
        except (FileNotFoundError, TypeError):
            image_data = ""

        html += f"""
            <div style='border: 1px solid #ddd; padding: 5px; text-align: center;'>
                <img src='{image_data}' width='150' height='150' style='object-fit: contain;'>
            </div>
        """
    html += "</div>"
    return html

def process_video(video_path, style, cols):
    output_dir = "faces_output"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    video_to_faces(input_path=video_path, style=style, out_dir=output_dir)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    upload_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO videos (filename, filepath, upload_date, fps) VALUES (?, ?, ?, ?)",
                   (os.path.basename(video_path), os.path.abspath(video_path), upload_date, fps))
    video_id = cursor.lastrowid

    face_images = glob.glob(os.path.join(output_dir, "**/*.jpg"), recursive=True)
    for image_path in face_images:
        face_image_path = os.path.abspath(image_path)
        try:
            cluster_id = int(os.path.basename(os.path.dirname(image_path)))
        except (ValueError, TypeError):
            cluster_id = -1

        filename_parts = os.path.basename(image_path).split('.')[0].split('_')
        frame_number = int(filename_parts[0])
        timestamp_seconds = frame_number / fps if fps > 0 else 0

        cursor.execute("INSERT INTO faces (video_id, frame_number, timestamp_seconds, face_image_path, cluster_id) VALUES (?, ?, ?, ?, ?)",
                       (video_id, frame_number, timestamp_seconds, face_image_path, cluster_id))

    conn.commit()
    conn.close()

    return update_galleries(cols)

def rename_face(face_id, new_name):
    if not face_id or not new_name:
        return "Please select a face and enter a new name."
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE faces SET person_name = ? WHERE id = ?", (new_name, face_id))
    conn.commit()
    count = cursor.rowcount
    conn.close()
    return f"Updated {count} face."

def merge_faces(face_ids, new_name):
    if not face_ids or not new_name:
        return "Please select faces and enter a new name."
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    face_ids_tuple = tuple(face_ids)
    cursor.execute(f"UPDATE faces SET person_name = ? WHERE id IN ({','.join(['?']*len(face_ids_tuple))})", (new_name, *face_ids_tuple))
    conn.commit()
    count = cursor.rowcount
    conn.close()
    return f"Merged {count} faces."

def clear_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM faces")
    cursor.execute("DELETE FROM videos")
    conn.commit()
    conn.close()
    return "Database cleared."

init_db()

with gr.Blocks() as demo:
    gr.Markdown("# Video to Faces")

    with gr.Tab("Organization"):
        with gr.Row():
            cols_dropdown = gr.Dropdown(label="Columns", choices=[3, 5, 8, 10], value=5)
        with gr.Tabs():
            with gr.TabItem("By Person"):
                person_galleries = gr.HTML()
            with gr.TabItem("By Video"):
                video_galleries = gr.HTML()
            with gr.TabItem("Chronological"):
                chrono_gallery = gr.HTML()

    with gr.Tab("Process Videos"):
        with gr.Row():
            with gr.Column(scale=1):
                video_input = gr.Video(label="Upload Video")
                style_input = gr.Radio(["live", "anime"], label="Style", value="live")
                submit_button = gr.Button("Submit")

    with gr.Tab("Manage Faces"):
        rename_state = gr.State()
        merge_state = gr.State([])
        with gr.Row():
            with gr.Column():
                gr.Markdown("## Rename Face")
                rename_gallery = gr.Gallery(label="Select Face to Rename", allow_preview=False)
                rename_name = gr.Textbox(label="New Name")
                rename_button = gr.Button("Rename")
                rename_status = gr.Textbox(label="Status", interactive=False)

            with gr.Column():
                gr.Markdown("## Merge Faces")
                merge_gallery = gr.Gallery(label="Select Faces to Merge", allow_preview=True)
                merge_name = gr.Textbox(label="Unified Name")
                merge_button = gr.Button("Merge")
                clear_merge_button = gr.Button("Clear Selection")
                merge_status = gr.Textbox(label="Status", interactive=False)

    with gr.Tab("Settings"):
        clear_db_button = gr.Button("Clear Database")
        clear_db_status = gr.Textbox(label="Status", interactive=False)

    def get_face_id_from_path(path):
        df = get_all_data()
        for index, row in df.iterrows():
            try:
                with open(path, 'rb') as f1:
                    with open(row['face_image_path'], 'rb') as f2:
                        if f1.read() == f2.read():
                            return int(row['face_id'])
            except (FileNotFoundError, TypeError):
                continue
        return None

    def set_rename_face(evt: gr.SelectData):
        return evt.value['image']['path']

    def rename_face_wrapper(face_path, name, cols):
        if not face_path or not name:
            return "Please select a face and enter a new name.", gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
        face_id = get_face_id_from_path(face_path)
        status = rename_face(face_id, name)
        return status, *update_galleries(cols)

    def add_to_merge_selection(evt: gr.SelectData, state):
        face_id = get_face_id_from_path(evt.value['image']['path'])
        if face_id and face_id not in state:
            state.append(face_id)
        return state, f"Selected {len(state)} faces."

    def merge_faces_wrapper(state, name, cols):
        status = merge_faces(state, name)
        return status, *update_galleries(cols), []

    def clear_merge_selection():
        return [], "Selection cleared."

    def clear_db_wrapper(cols):
        status = clear_database()
        return status, *update_galleries(cols), gr.update(choices=["All"])

    def update_galleries(cols):
        df = get_all_data()
        person_html = ""
        for person, group in df.groupby('name'):
            person_html += f"<h3>{person} ({len(group)} faces)</h3>"
            person_html += create_gallery_html(group, cols)
        video_html = ""
        for video, group in df.groupby('video_filename'):
            video_html += f"<h3>{video}</h3>"
            video_html += create_gallery_html(group, cols)
        chrono_df = df.sort_values(by=['upload_date', 'timestamp_seconds'])
        chrono_html = create_gallery_html(chrono_df, cols)
        return person_html, video_html, chrono_html, gr.update(value=[f['face_image_path'] for i, f in df.iterrows()]), gr.update(value=[f['face_image_path'] for i, f in df.iterrows()])

    submit_button.click(
        fn=process_video,
        inputs=[video_input, style_input, cols_dropdown],
        outputs=[person_galleries, video_galleries, chrono_gallery, rename_gallery, merge_gallery]
    )

    cols_dropdown.change(fn=update_galleries, inputs=[cols_dropdown], outputs=[person_galleries, video_galleries, chrono_gallery, rename_gallery, merge_gallery])

    rename_gallery.select(fn=set_rename_face, inputs=None, outputs=[rename_state])
    rename_button.click(fn=rename_face_wrapper, inputs=[rename_state, rename_name, cols_dropdown], outputs=[rename_status, person_galleries, video_galleries, chrono_gallery, rename_gallery, merge_gallery])
    merge_gallery.select(fn=add_to_merge_selection, inputs=[merge_state], outputs=[merge_state, merge_status])
    merge_button.click(fn=merge_faces_wrapper, inputs=[merge_state, merge_name, cols_dropdown], outputs=[merge_status, person_galleries, video_galleries, chrono_gallery, rename_gallery, merge_gallery, merge_state])
    clear_merge_button.click(fn=clear_merge_selection, inputs=None, outputs=[merge_state, merge_status])
    clear_db_button.click(fn=clear_db_wrapper, inputs=[cols_dropdown], outputs=[clear_db_status, person_galleries, video_galleries, chrono_gallery, rename_gallery, merge_gallery])

    demo.load(lambda cols: update_galleries(cols), inputs=[cols_dropdown], outputs=[person_galleries, video_galleries, chrono_gallery, rename_gallery, merge_gallery])

app = gr.mount_gradio_app(app, demo, path="/")
