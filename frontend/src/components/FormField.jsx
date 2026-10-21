import { cloneElement, isValidElement, useId } from 'react';

/**
 * Label + control + error/hint wrapper. The child control receives the id
 * and aria attributes automatically.
 *
 * @param {{label: string, error?: string, hint?: string, required?: boolean,
 *          children: React.ReactElement, className?: string}} props
 */
export default function FormField({ label, error, hint, required = false, children, className = '' }) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  const control = isValidElement(children)
    ? cloneElement(children, {
      id,
      'aria-invalid': error ? true : undefined,
      'aria-describedby': describedBy,
      required: children.props.required ?? required,
    })
    : children;

  return (
    <div className={`field ${error ? 'field-invalid' : ''} ${className}`}>
      <label htmlFor={id}>
        {label}
        {required && <span className="required" aria-hidden="true"> *</span>}
      </label>
      {control}
      {error && <p className="field-error" id={`${id}-error`}>{capitalise(error)}</p>}
      {!error && hint && <p className="field-hint" id={`${id}-hint`}>{hint}</p>}
    </div>
  );
}

function capitalise(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
