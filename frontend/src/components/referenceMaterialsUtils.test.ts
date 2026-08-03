import { describe, expect, it } from 'vitest';

import type { StoryBible } from '../api';
import {
  buildReferenceMaterialPayload,
  buildReferenceMaterialSummary,
  createReferenceMaterialForm,
  referenceMaterialGroupCount,
} from './referenceMaterialsUtils';

describe('参考写作资料提炼', () => {
  it('将作者画像转成普通作者可执行的写作规划', () => {
    const summary = buildReferenceMaterialSummary({
      deconstruction_7: { title: '匿名参考作品' },
      reference_author_profile: {
        schema_version: '2.0',
        sampled_chapters: [1, 3, 5],
        source_label: '匿名样本',
        confidence: 0.9,
        style_profile: {
          sentence: { general: '以短句推进动作，关键转折使用长句蓄势' },
          dialogue: { general: '对话承担冲突，不重复解释人物情绪' },
          description: { general: '优先描写可感知细节' },
          emotion_expression: { general: '用动作和停顿呈现情绪' },
          pov_and_narration: { general: '限制视角，跟随主角认知释放信息' },
        },
        rhythm_profile: {
          opening_hook: { general: '开篇先给异常事件' },
          chapter_end_hooks: ['新威胁', '未完成行动'],
          emotion_cycle: { general: '压迫、反击、短暂释放' },
          info_release_pattern: { general: '答案与新问题成对出现' },
        },
        routine_cards: [{
          name: '误判反转',
          category: '冲突',
          structure: '建立判断，再用行动证据推翻',
          emotion_curve: '疑惑到紧张再到释然',
          evidence_summary: '适合章中转折',
        }],
        writing_guide: {
          do: ['每章让主角做出主动选择'],
          avoid: ['避免总结式情绪说明'],
          prompt_notes: ['保持场景目标明确'],
        },
      },
      reference_author_report: '# 原始报告\n完整分析内容',
      reference_style_samples: [{ chapter: 18, snippet: '样本文字' }],
      learned_techniques: [{ name: '场景内转折', description: '在目标即将达成时改变阻力' }],
    } as StoryBible);

    expect(summary.expressionPlan.map((item) => item.label)).toEqual(['句式节奏', '对话组织', '描写方式', '情绪表达', '叙事视角']);
    expect(summary.rhythmPlan.map((item) => item.label)).toEqual(['开篇抓力', '章尾钩子', '情绪循环', '信息释放']);
    expect(summary.sampledChapterCount).toBe(3);
    expect(summary.confidencePercent).toBe(90);
    expect(summary.mustDo).toEqual(['每章让主角做出主动选择']);
    expect(summary.routines[0]?.name).toBe('误判反转');
    expect(summary.report).toContain('完整分析内容');
    expect(summary.samples).toEqual([{ label: '风格样本 1', snippet: '样本文字' }]);
    expect(JSON.stringify(summary)).not.toContain('schema_version');
    expect(JSON.stringify(summary.samples)).not.toContain('18');
    expect(referenceMaterialGroupCount(summary)).toBeGreaterThan(0);
  });

  it('兼容旧报告字段并正确识别无资料状态', () => {
    expect(buildReferenceMaterialSummary({
      reference_author_profile: { manual_override: true },
      reference_report: '旧版报告',
    } as StoryBible).report).toBe('旧版报告');
    expect(buildReferenceMaterialSummary({
      reference_author_profile: { manual_override: true, writing_guide: { prompt_notes: ['保持场景目标明确'] } },
    } as StoryBible).hasContent).toBe(true);
    expect(buildReferenceMaterialSummary({} as StoryBible).hasContent).toBe(false);
  });

  it('识别用户主动应用的旧版拆书结果', () => {
    const summary = buildReferenceMaterialSummary({
      deconstruction: { result_id: 7, source: { title: '本作品拆书结果' } },
      reference_report: '用户主动应用的拆书报告',
      learned_techniques: [{ name: '场景转折' }],
    } as StoryBible);

    expect(summary.hasContent).toBe(true);
    expect(summary.report).toBe('用户主动应用的拆书报告');
    expect(summary.learnedTechniques).toEqual([{ name: '场景转折' }]);
  });

  it('保存人工修订时保留画像元数据和字段例外规则', () => {
    const bible = {
      deconstruction_8: { title: '匿名参考作品' },
      reference_author_profile: {
        schema_version: '2.0',
        sampled_chapters: [1, 2, 3],
        style_profile: {
          sentence: { general: '原句式', exceptions: ['高潮可用长句'] },
        },
        rhythm_profile: {
          chapter_end_hooks: ['旧钩子'],
        },
        writing_guide: { do: ['旧要求'], custom_rule: '保留字段' },
        routine_cards: [{ id: 'routine-1', name: '旧模式', structure: '旧结构' }],
      },
      reference_report: '旧版报告',
    } as StoryBible;
    const form = createReferenceMaterialForm(bible);
    form.sentence = '更新后的句式规划';
    form.chapterEndHooks = '悬念中断\n行动受阻';
    form.mustDo = '每章包含主动选择\n场景目标明确';
    form.report = '人工修订后的报告';
    form.routines = [{ name: '压力升级', category: '冲突', structure: '两次加压', emotionCurve: '紧张上升', evidence: '适合中段' }];

    const payload = buildReferenceMaterialPayload(bible, form);
    const profile = payload.reference_author_profile as Record<string, unknown>;
    const styleProfile = profile.style_profile as Record<string, unknown>;
    const rhythmProfile = profile.rhythm_profile as Record<string, unknown>;
    const writingGuide = profile.writing_guide as Record<string, unknown>;
    const routineCards = profile.routine_cards as Array<Record<string, unknown>>;
    expect(profile.schema_version).toBe('2.0');
    expect(profile.manual_override).toBe(true);
    expect(profile.sampled_chapters).toEqual([1, 2, 3]);
    expect(styleProfile.sentence).toEqual({ general: '更新后的句式规划', exceptions: ['高潮可用长句'] });
    expect(rhythmProfile.chapter_end_hooks).toEqual(['悬念中断', '行动受阻']);
    expect(writingGuide).toMatchObject({ do: ['每章包含主动选择', '场景目标明确'], custom_rule: '保留字段' });
    expect(routineCards[0]).toMatchObject({ id: 'routine-1', name: '压力升级', emotion_curve: '紧张上升' });
    expect(payload.reference_report).toBe('人工修订后的报告');
    expect(payload).not.toHaveProperty('reference_author_report');
  });

  it('没有引用或人工修订时忽略历史残留画像', () => {
    const staleBible = {
      reference_author_profile: {
        style_profile: { sentence: { general: '不应继续生效的旧风格' } },
      },
      reference_author_report: '不应继续注入的旧报告',
      reference_style_samples: [{ snippet: '旧样本' }],
    } as StoryBible;

    expect(buildReferenceMaterialSummary(staleBible).hasContent).toBe(false);
    expect(createReferenceMaterialForm(staleBible).sentence).toBe('');

    const form = createReferenceMaterialForm(staleBible);
    form.sentence = '用户主动填写的新风格';
    const payload = buildReferenceMaterialPayload(staleBible, form);
    expect((payload.reference_author_profile as Record<string, unknown>).manual_override).toBe(true);
    expect(payload.reference_style_samples).toEqual([]);
  });
});
