from pathlib import Path
import importlib.util, json, sys, time
import win32com.client
import pypdfium2 as pdfium

ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'Word/materials/thesis_update'
OUT=ROOT/'Word/本科毕业论文_基于TensorFlow的智能电网负荷预测系统设计与实现_项目更新排版版.docx'
PDF=WORK/'review.pdf'
tag=sys.argv[1] if len(sys.argv)>1 else 'render_v1'
png_dir=WORK/tag
png_dir.mkdir(parents=True,exist_ok=True)
word=win32com.client.DispatchEx('Word.Application')
word.Visible=False
word.DisplayAlerts=0
opened=None
try:
    opened=word.Documents.Open(str(OUT),ReadOnly=False,AddToRecentFiles=False)
    opened.Repaginate()
    opened.Fields.Update()
    for toc in opened.TablesOfContents:
        toc.Update()
    opened.Repaginate()
    for toc in opened.TablesOfContents:
        toc.UpdatePageNumbers()
    opened.Save()
    pages=opened.ComputeStatistics(2)
    opened.ExportAsFixedFormat(str(PDF),17,False,0,0,0,0,0,True,False,0,True,True,True)
    print(json.dumps({'word_pages':pages,'toc_count':opened.TablesOfContents.Count,'pdf':str(PDF)},ensure_ascii=False),flush=True)
finally:
    if opened is not None:opened.Close(False)
    word.Quit()

# The packaged Windows renderer has no bundled LibreOffice. Word performs layout
# and export; the canonical renderer still supplies the PDF-to-PNG stage.
renderer_path=Path('C:/Users/ygz/.codex/plugins/cache/openai-primary-runtime/documents/26.909.12148/skills/documents/render_docx.py')
spec=importlib.util.spec_from_file_location('canonical_docx_renderer',renderer_path)
renderer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)
renderer.convert_to_pdf=lambda *args,**kwargs:(str(PDF),'Microsoft Word native export; no LibreOffice dependency')
paths=renderer.rasterize(str(OUT),str(png_dir),144,False,False)
pdf=pdfium.PdfDocument(str(PDF))
texts=[]
for n,page in enumerate(pdf):
    textpage=page.get_textpage()
    txt=textpage.get_text_range()
    texts.append({'page':n+1,'text':txt,'characters':len(txt)})
    # Poppler on this Windows host intermittently omits some embedded glyphs.
    # PDFium cross-check preserves them and provides the final review rasters.
    page.render(scale=2).to_pil().save(png_dir/('page-'+str(n+1)+'.png'))
(WORK/(tag+'_page_text.json')).write_text(json.dumps(texts,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'rendered_pages':len(paths),'png_directory':str(png_dir)},ensure_ascii=False),flush=True)
