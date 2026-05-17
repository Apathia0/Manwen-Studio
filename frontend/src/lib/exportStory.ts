import JSZip from 'jszip';
import { saveAs } from 'file-saver';
import type { Chapter, Story } from '../api';

export interface ExportData {
  story: Story;
  chapters: Chapter[];
}

export async function exportStoryAsZip(data: ExportData): Promise<void> {
  const { story, chapters } = data;
  const dateStr = new Date().toISOString().slice(0, 10);
  const zip = new JSZip();
  const baseTitle = sanitizeName(story.title || '未命名作品');
  const folderName = `${baseTitle}_导出文件_${dateStr}`;

  zip.file(`${folderName}/小说数据备份.json`, JSON.stringify(buildJsonBackup(story, chapters), null, 2));
  zip.file(`${folderName}/小说正文.md`, buildMainNovelMd(story, chapters));

  if (story.outline) {
    zip.file(`${folderName}/01_故事大纲.md`, buildOutlineMd(story));
  }

  if (story.characters && story.characters.length > 0) {
    zip.file(`${folderName}/02_角色设定.md`, buildCharactersMd(story));
  }

  const chapterFolder = zip.folder(`${folderName}/03_章节正文`);
  if (chapterFolder) {
    for (const chapter of chapters) {
      const chapterTitle = chapter.title || `第${chapter.chapter_number}章`;
      const safeName = sanitizeName(
        `第${String(chapter.chapter_number).padStart(2, '0')}章_${chapterTitle}.md`,
      );
      chapterFolder.file(safeName, buildChapterMd(chapter));
    }
  }

  const blob = await zip.generateAsync({ type: 'blob' });
  saveAs(blob, `${baseTitle}_导出文件_${dateStr}.zip`);
}

function sanitizeName(value: string): string {
  return value.replace(/[\\/:*?"<>|]/g, '_');
}

function buildJsonBackup(story: Story, chapters: Chapter[]) {
  return {
    version: 1,
    exported_at: new Date().toISOString(),
    story: {
      title: story.title,
      description: story.description || '',
      tags: story.tags || {},
      characters: story.characters || [],
      outline: story.outline || {},
    },
    chapters: chapters.map((chapter) => ({
      chapter_number: chapter.chapter_number,
      title: chapter.title || '',
      act: chapter.act || '',
      status: chapter.status || 'pending',
      novel_content: chapter.novel_content || '',
      key_events: chapter.key_events || [],
      word_count: chapter.word_count || 0,
      quality_score: chapter.quality_score || null,
    })),
  };
}

function buildMainNovelMd(story: Story, chapters: Chapter[]): string {
  let md = `# ${story.title}\n\n`;
  if (story.description?.trim()) {
    md += `> ${story.description}\n\n`;
  }
  md += `---\n\n`;
  for (const chapter of chapters) {
    const title = chapter.title || `Chapter ${chapter.chapter_number}`;
    md += `## ${title}\n\n`;
    if (chapter.novel_content?.trim()) {
      md += `${chapter.novel_content}\n\n`;
    }
    md += `---\n\n`;
  }
  return md.trim();
}

function buildOutlineMd(story: Story): string {
  const outline = story.outline;
  let md = `# Outline - ${story.title}\n\n`;
  if (outline?.themes?.length) {
    md += `**Themes**: ${outline.themes.join(', ')}\n\n`;
  }

  const acts = outline?.three_acts as any[] | undefined;
  if (acts) {
    for (let i = 0; i < acts.length; i += 1) {
      const act = acts[i];
      const actTitle = act?.title || act?.name || `Phase ${i + 1}`;
      md += `## ${actTitle}\n\n`;
      if (act?.summary) {
        md += `> ${act.summary}\n\n`;
      }
      const phaseChapters = Array.isArray(act?.chapters) ? act.chapters : [];
      for (const chapter of phaseChapters) {
        md += `### ${chapter.title || `Chapter ${chapter.chapter_number}`}\n\n`;
        if (chapter.summary) {
          md += `${chapter.summary}\n\n`;
        }
        if (Array.isArray(chapter.key_events) && chapter.key_events.length > 0) {
          for (const item of chapter.key_events) {
            md += `- ${item}\n`;
          }
          md += `\n`;
        }
      }
    }
  }

  if (Array.isArray(outline?.foreshadowing) && outline.foreshadowing.length > 0) {
    md += `## Foreshadowing\n\n`;
    for (const item of outline.foreshadowing) {
      md += `- ${typeof item === 'string' ? item : JSON.stringify(item)}\n`;
    }
  }

  return md.trim();
}

function buildCharactersMd(story: Story): string {
  const characters = story.characters || [];
  let md = `# Characters - ${story.title}\n\n`;
  md += `${characters.length} character(s)\n\n---\n\n`;

  for (const character of characters) {
    md += `## ${character.name || 'Unnamed Character'}\n\n`;
    if (character.role) {
      md += `**Role**: ${character.role}\n\n`;
    }
    if (character.big_five) {
      md += `**Big Five**\n\n`;
      const labels: Record<string, string> = {
        O: 'Openness',
        C: 'Conscientiousness',
        E: 'Extraversion',
        A: 'Agreeableness',
        N: 'Neuroticism',
      };
      for (const [key, label] of Object.entries(labels)) {
        const value = (character.big_five as any)[key];
        if (value !== undefined) {
          md += `- ${label}: ${value}\n`;
        }
      }
      md += `\n`;
    }
    if (character.arc?.motivation) {
      md += `**Motivation**: ${character.arc.motivation}\n\n`;
    }
    if (character.arc?.fear) {
      md += `**Fear**: ${character.arc.fear}\n\n`;
    }
    if (Array.isArray(character.relationships) && character.relationships.length > 0) {
      md += `**Relationships**\n\n`;
      for (const relation of character.relationships) {
        md += `- ${relation.character || '?'}: ${relation.relationship || '?'}\n`;
      }
      md += `\n`;
    }
    md += `---\n\n`;
  }

  return md.trim();
}

function buildChapterMd(chapter: Chapter): string {
  const title = chapter.title || `Chapter ${chapter.chapter_number}`;
  let md = `# ${title}\n\n`;
  if (chapter.act) {
    md += `> Phase ${chapter.act}\n\n`;
  }
  if (chapter.novel_content?.trim()) {
    md += `${chapter.novel_content}\n\n`;
  }
  if (Array.isArray(chapter.key_events) && chapter.key_events.length > 0) {
    md += `**Key Events**\n\n`;
    for (const item of chapter.key_events) {
      md += `- ${item}\n`;
    }
  }
  return md.trim();
}
