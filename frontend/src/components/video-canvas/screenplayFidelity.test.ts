import { describe, expect, it } from 'vitest';
import { analyzeFidelity, findSourceParagraph, splitParagraphs } from './screenplayFidelity';

const SOURCE = [
  '“斗之力，三段！级别：低级！”测验员漠然地宣布。',
  '萧炎站在魔石碑前，面无表情，唇角挂着一抹自嘲。他缓缓抬起头，扫过周围嘲讽的人群。',
  '“萧炎哥哥。”萧薰儿微微弯下腰，露出清澈的笑容。',
].join('\n');

describe('analyzeFidelity', () => {
  it('忠实的台词标 ok，改写的标 changed，原文里没有的标 new，并找出凭空多出来的人物', () => {
    const script = [
      '场景1：萧家广场 / 日 / 外景',
      '测验员（漠然）：萧炎，斗之力，三段！级别：低级！',
      '萧薰儿：萧炎哥哥。',
      '管家：老爷请您立刻回府，有一笔三亿的账需要当场清算！',
    ].join('\n');
    const report = analyzeFidelity(script, SOURCE);
    expect(report.lines[0].kind).toBe('header');
    const dialogues = report.lines.filter((line) => line.kind === 'dialogue');
    expect(dialogues[0].speaker).toBe('测验员');
    expect(dialogues[0].status).toBe('ok');
    expect(dialogues[1].status).toBe('ok');
    expect(dialogues[2].status).toBe('new');
    expect(report).toMatchObject({ dialogueTotal: 3, dialogueOk: 2, dialogueNew: 1 });
    expect(report.newSpeakers).toEqual(['管家']);
  });

  it('动作行说法不同也不乱报，只标几乎完全对不上的', () => {
    const report = analyzeFidelity('萧炎站在魔石碑前，面无表情，缓缓抬头。\n一辆黑色轿车停在街对面，车灯忽然亮起。', SOURCE);
    expect(report.lines[0].status).toBe('ok');
    expect(report.lines[1].status).toBe('new');
    expect(report.actionNew).toBe(1);
  });

  it('点击剧本的一句，能在原文里找到最对应的段落', () => {
    const paragraphs = splitParagraphs(SOURCE);
    expect(findSourceParagraph('萧薰儿：萧炎哥哥。', paragraphs)).toBe(2);
    expect(findSourceParagraph('一辆黑色轿车停在街对面', paragraphs)).toBe(-1);
  });
});
