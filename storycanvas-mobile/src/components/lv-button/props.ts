export interface ButtonProps {
  type?: 'primary' | 'secondary' | 'text' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
  disabled?: boolean
  block?: boolean
}

export const defaultButtonProps: ButtonProps = {
  type: 'primary',
  size: 'md',
  loading: false,
  disabled: false,
  block: false
}
