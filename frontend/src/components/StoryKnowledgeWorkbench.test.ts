import { describe, expect, it } from 'vitest';

import type { StoryBible } from '../api';
import { buildAISyncNotice } from './StoryKnowledgeWorkbench';
import {
  buildStoryBiblePayload,
  collectBibleSections,
  createStoryBibleFormState,
  worldSettingRowsToObject,
  worldSettingToRows,
} from './storyBibleUtils';

const legacyBible: StoryBible = {
  creative_brief: {
    作品定位: '灾后自然退化高武世界',
    题材: '正统高武',
    主线矛盾: '重建仙道根基',
    必保留设定: '无系统\n无外挂',
    世界观设定: {
      世界历史: '上古仙战导致仙道断绝',
    },
    旧版扩展字段: '必须保留',
  } as unknown as StoryBible['creative_brief'],
  writing_guidance: {
    开书策略: '三章内完成核心卖点展示',
    核心铁律: '每章至少一个主动决策',
  },
  import_guidance: {
    导入素材类型: '完整大纲',
    风格护栏: '禁止 AI 味用词',
  },
  reference_author_profile: {
    style_profile: { sentence: '多用短句' },
  },
  reference_author_report: '匿名作者写作风格学习报告',
  reference_style_samples: [{ title: '样本一', excerpt: '示例正文' }],
};

describe('AI 同步结果展示', () => {
  it('将部分成功结果显示为可持续查看的警告', () => {
    const notice = buildAISyncNotice({
      task_id: 'knowledge_sync_12_test',
      task_type: 'knowledge_ai_sync',
      status: 'succeeded',
      result_json: {
        message: '已保存本次完成的 14 组内容，另有 1 组将在下次同步时继续补充',
        successful_sources: 14,
        failed_sources: 1,
        counts: { entities: 8, facts: 20, plot_threads: 3, archived_facts: 2 },
      },
    });

    expect(notice).toEqual({
      tone: 'warning',
      message: '已保存本次完成的 14 组内容，另有 1 组将在下次同步时继续补充',
      details: '实体 8 · 事实 20 · 伏笔 3 · 归档旧事实 2',
    });
  });

  it('恢复最近一次失败结果', () => {
    expect(buildAISyncNotice({
      task_id: 'knowledge_sync_12_failed',
      task_type: 'knowledge_ai_sync',
      status: 'failed',
      error_message: '同步超时，已保留完成内容',
      metadata_json: { completed: 14, total: 15 },
    })).toEqual({
      tone: 'error',
      message: '同步超时，已保留完成内容',
      details: '已处理 14/15 组内容，本次未生成可保存结果',
    });
  });
});

describe('作品设定中心兼容旧版作品圣经', () => {
  it('读取旧版中文字段并拆分展示世界观', () => {
    const form = createStoryBibleFormState(legacyBible);
    const sections = collectBibleSections(legacyBible);

    expect(form.project_positioning).toBe('灾后自然退化高武世界');
    expect(form.opening_strategy).toBe('三章内完成核心卖点展示');
    expect(form.import_material_type).toBe('完整大纲');
    const sectionKeys = sections.map((section) => section.key);
    expect(sectionKeys).toEqual(expect.arrayContaining([
      'creative_brief',
      'writing_guidance',
      'world_setting',
      'import_guidance',
    ]));
    expect(sectionKeys).not.toContain('reference_author_profile');
    expect(sectionKeys).not.toContain('reference_author_report');
    expect(sectionKeys).not.toContain('reference_style_samples');
    expect(sections.find((section) => section.key === 'world_setting')?.value).toEqual({
      世界历史: '上古仙战导致仙道断绝',
    });
  });

  it('保存时沿用中文键且不重复提交只读参考资料', () => {
    const form = createStoryBibleFormState(legacyBible);
    form.project_positioning = '更新后的作品定位';
    form.tone_guardrails = '更新后的风格护栏';

    const payload = buildStoryBiblePayload(form, legacyBible, {
      世界历史: '更新后的世界历史',
    });

    expect(payload.creative_brief?.['作品定位']).toBe('更新后的作品定位');
    expect(payload.creative_brief?.project_positioning).toBeUndefined();
    expect(payload.creative_brief?.['旧版扩展字段']).toBe('必须保留');
    expect(payload.import_guidance?.['风格护栏']).toBe('更新后的风格护栏');
    expect(payload).not.toHaveProperty('reference_author_profile');
    expect(payload).not.toHaveProperty('reference_author_report');
    expect(payload).not.toHaveProperty('reference_style_samples');
  });

  it('世界观未编辑时保留嵌套类型，删除字段时不再写回', () => {
    const original = {
      地图: { 城市: ['临海城', '北境城'] },
      纪元: 100,
      是否末法: true,
    };
    let nextId = 0;
    const rows = worldSettingToRows(original, () => `row-${nextId++}`);

    expect(worldSettingRowsToObject(rows)).toEqual(original);
    expect(worldSettingRowsToObject(rows.filter((row) => row.key !== '纪元'))).toEqual({
      地图: original.地图,
      是否末法: true,
    });

    const edited = rows.map((row) => row.key === '纪元' ? { ...row, value: '新纪元' } : row);
    expect(worldSettingRowsToObject(edited).纪元).toBe('新纪元');
  });
});
