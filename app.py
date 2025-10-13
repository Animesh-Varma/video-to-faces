
import gradio as gr
import os
import glob
import sqlite3
import cv2
import datetime
import pandas as pd
import base64
from videotofaces import video_to_faces

DB_FILE = "faces_db.sqlite"

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

        video_link = f"{row['video_filepath']}#t={int(row['timestamp_seconds'])}"
        html += f"""
            <div style='border: 1px solid #ddd; padding: 5px; text-align: center;'>
                <img src='{image_data}' width='150' height='150' style='object-fit: cover;'>
                <p style='font-size: 12px; margin: 5px 0 0 0;'>{row['video_filename']}</p>
                <a href='file://{video_link}' target='_blank' style='font-size: 12px;'>{format_timestamp(row['timestamp_seconds'])}</a>
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
    return create_html_grid(df), gr.update(choices=["All"] + list(df['video_filename'].unique()))

def filter_faces(video_filter, name_filter):
    df = get_all_data()
    if video_filter != "All":
        df = df[df['video_filename'] == video_filter]
    if name_filter:
        df = df[df['name'].str.contains(name_filter, case=False, na=False)]
    return create_html_grid(df)

init_db()

with gr.Blocks() as demo:
    gr.Markdown("# Video to Faces")
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

    submit_button.click(
        fn=process_video,
        inputs=[video_input, style_input],
        outputs=[face_display, video_filter]
    )

    video_filter.change(fn=filter_faces, inputs=[video_filter, name_filter], outputs=face_display)
    name_filter.change(fn=filter_faces, inputs=[video_filter, name_filter], outputs=face_display)

    demo.load(lambda: gr.update(choices=["All"] + list(get_all_data()['video_filename'].unique())), None, video_filter)

if __name__ == "__main__":
    demo.launch(share=True)
