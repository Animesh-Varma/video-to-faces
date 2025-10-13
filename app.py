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
            COALESCE(f.person_name, 'Cluster ' || f.cluster_id) AS name
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

def create_html_grid(df):
    if df.empty:
        return "<p>No faces to display.</p>"
    html = "<div style='display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px;'>"
    for _, row in df.iterrows():
        try:
            with open(row['face_image_path'], 'rb') as img_file:
                encoded_string = base64.b64encode(img_file.read()).decode('utf-8')
            image_data = f"data:image/jpeg;base64,{encoded_string}"
        except (FileNotFoundError, TypeError):
            image_data = ""

        video_link = f"/files/{urllib.parse.quote(row['video_filepath'])}#t={int(row['timestamp_seconds'])}"
        html += f"""
            <div style='border: 1px solid #ddd; padding: 5px; text-align: center;'>
                <img src='{image_data}' width='150' height='150' style='object-fit: cover;' alt='{row['face_id']}'>
                <p style='font-size: 12px; margin: 5px 0 0 0;'>{row['video_filename']}</p>
                <a href='{video_link}' target='_blank' style='font-size: 12px;'>{format_timestamp(row['timestamp_seconds'])}</a>
                <p style='font-size: 12px; margin: 5px 0 0 0;'>{row['name']}</p>
            </div>
        """
    html += "</div>"
    return html

def process_video(video_path, style):
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

    df = get_all_data()
    return create_html_grid(df), gr.update(choices=["All"] + list(df['video_filename'].unique())), gr.update(value=[f['face_image_path'] for i, f in df.iterrows()]), gr.update(value=[f['face_image_path'] for i, f in df.iterrows()])

def filter_faces(video_filter, name_filter):
    df = get_all_data()
    if video_filter != "All":
        df = df[df['video_filename'] == video_filter]
    if name_filter:
        df = df[df['name'].str.contains(name_filter, case=False, na=False)]
    return create_html_grid(df)

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
    with gr.Tab("Process Videos"):
        with gr.Row():
            with gr.Column(scale=1):
                video_input = gr.Video(label="Upload Video")
                style_input = gr.Radio(["live", "anime"], label="Style", value="live")
                submit_button = gr.Button("Submit")

        with gr.Row():
            with gr.Column(scale=1):
                video_filter = gr.Dropdown(label="Filter by Video", choices=["All"] + list(get_all_data()['video_filename'].unique()), value="All")
                name_filter = gr.Textbox(label="Filter by Name/Cluster ID")

        with gr.Row():
            face_display = gr.HTML(create_html_grid(get_all_data()))

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
        # The path from the gallery will be a temporary file path, so we need to find the original path
        # by matching the image content. This is not ideal, but it's a workaround.
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

    def rename_face_wrapper(face_path, name):
        if not face_path or not name:
            return "Please select a face and enter a new name.", create_html_grid(get_all_data())
        face_id = get_face_id_from_path(face_path)
        status = rename_face(face_id, name)
        df = get_all_data()
        return status, create_html_grid(df), gr.update(value=[f['face_image_path'] for i, f in df.iterrows()]), gr.update(value=[f['face_image_path'] for i, f in df.iterrows()])

    def add_to_merge_selection(evt: gr.SelectData, state):
        face_id = get_face_id_from_path(evt.value['image']['path'])
        if face_id and face_id not in state:
            state.append(face_id)
        return state, f"Selected {len(state)} faces."

    def merge_faces_wrapper(state, name):
        status = merge_faces(state, name)
        df = get_all_data()
        return status, create_html_grid(df), [], gr.update(value=[f['face_image_path'] for i, f in df.iterrows()]), gr.update(value=[f['face_image_path'] for i, f in df.iterrows()])

    def clear_merge_selection():
        return [], "Selection cleared."

    def clear_db_wrapper():
        status = clear_database()
        df = get_all_data()
        return status, create_html_grid(df), gr.update(choices=["All"]), gr.update(value=[]), gr.update(value=[])

    submit_button.click(
        fn=process_video,
        inputs=[video_input, style_input],
        outputs=[face_display, video_filter, rename_gallery, merge_gallery]
    )

    video_filter.change(fn=filter_faces, inputs=[video_filter, name_filter], outputs=face_display)
    name_filter.change(fn=filter_faces, inputs=[video_filter, name_filter], outputs=face_display)

    rename_gallery.select(fn=set_rename_face, inputs=None, outputs=[rename_state])
    rename_button.click(fn=rename_face_wrapper, inputs=[rename_state, rename_name], outputs=[rename_status, face_display, rename_gallery, merge_gallery])
    merge_gallery.select(fn=add_to_merge_selection, inputs=[merge_state], outputs=[merge_state, merge_status])
    merge_button.click(fn=merge_faces_wrapper, inputs=[merge_state, merge_name], outputs=[merge_status, face_display, merge_state, rename_gallery, merge_gallery])
    clear_merge_button.click(fn=clear_merge_selection, inputs=None, outputs=[merge_state, merge_status])
    clear_db_button.click(fn=clear_db_wrapper, inputs=None, outputs=[clear_db_status, face_display, video_filter, rename_gallery, merge_gallery])

    demo.load(lambda: (
        gr.update(choices=["All"] + list(get_all_data()['video_filename'].unique())),
        gr.update(value=[f['face_image_path'] for i, f in get_all_data().iterrows()]),
        gr.update(value=[f['face_image_path'] for i, f in get_all_data().iterrows()])
    ), None, [video_filter, rename_gallery, merge_gallery])

app = gr.mount_gradio_app(app, demo, path="/")