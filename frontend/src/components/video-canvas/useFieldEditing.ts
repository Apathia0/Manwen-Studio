import { useCallback, useRef, useState } from 'react';
import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react';

/**
 * click-to-edit 行内编辑共享 hook。
 * 从 ChapterVideoWorkflowPanel 的 editingField 状态机模式抽象：
 * 字段 key 为字符串（如 "1.title"、"1.2.action"），同一时刻只编辑一个字段。
 * 提交时把原始字符串交给调用方回调写回（回调内自行做形态变换，如逗号拆分）。
 */

export type FieldSubmit = (rawValue: string) => void;

export interface FieldEditing {
  /** 当前正在编辑的字段 key；null 表示无 */
  editingField: string | null;
  /** 开始 / 结束编辑（传 null 结束） */
  setEditingField: (field: string | null) => void;
  /** input 类字段：Enter 提交、Esc 取消、blur 提交 */
  makeInputProps: (
    fieldKey: string,
    onSubmit: FieldSubmit,
    currentValue: string,
  ) => InputHTMLAttributes<HTMLInputElement>;
  /** textarea 类字段：仅 blur 提交（保留换行）、Esc 取消（阻止冒泡） */
  makeTextareaProps: (
    fieldKey: string,
    onSubmit: FieldSubmit,
    currentValue: string,
  ) => TextareaHTMLAttributes<HTMLTextAreaElement>;
}

export function useFieldEditing(): FieldEditing {
  const [editingField, setEditingFieldState] = useState<string | null>(null);
  // 镜像当前编辑 key：Enter/Esc 处理后置空，随后（若触发）的 blur 不再重复提交
  const activeKeyRef = useRef<string | null>(null);

  const setEditingField = useCallback((field: string | null) => {
    activeKeyRef.current = field;
    setEditingFieldState(field);
  }, []);

  const makeInputProps = useCallback(
    (fieldKey: string, onSubmit: FieldSubmit, currentValue: string): InputHTMLAttributes<HTMLInputElement> => ({
      autoFocus: true,
      defaultValue: currentValue,
      // 画布节点内使用：阻止冒泡，避免触发节点拖拽 / 头部折叠
      onClick: (event) => event.stopPropagation(),
      onPointerDown: (event) => event.stopPropagation(),
      onBlur: (event) => {
        if (activeKeyRef.current === fieldKey) {
          activeKeyRef.current = null;
          onSubmit(event.target.value);
          setEditingFieldState(null);
        }
      },
      onKeyDown: (event) => {
        if (event.key === 'Enter') {
          activeKeyRef.current = null;
          onSubmit(event.currentTarget.value);
          setEditingFieldState(null);
        } else if (event.key === 'Escape') {
          event.stopPropagation();
          setEditingField(null);
        }
      },
    }),
    [setEditingField],
  );

  const makeTextareaProps = useCallback(
    (fieldKey: string, onSubmit: FieldSubmit, currentValue: string): TextareaHTMLAttributes<HTMLTextAreaElement> => ({
      autoFocus: true,
      defaultValue: currentValue,
      onClick: (event) => event.stopPropagation(),
      onPointerDown: (event) => event.stopPropagation(),
      onBlur: (event) => {
        if (activeKeyRef.current === fieldKey) {
          activeKeyRef.current = null;
          onSubmit(event.target.value);
          setEditingFieldState(null);
        }
      },
      onKeyDown: (event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          event.stopPropagation();
          setEditingField(null);
        }
      },
    }),
    [setEditingField],
  );

  return { editingField, setEditingField, makeInputProps, makeTextareaProps };
}
