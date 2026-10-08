import { dirname, relative, resolve } from 'node:path';
import ts from 'typescript';
export type BoundaryLayer = 'web' | 'domain' | 'application';
const allowedPackages: Record<BoundaryLayer, readonly string[]> = {
  web: ['contracts', 'ui'],
  domain: ['domain'],
  application: ['application', 'contracts', 'domain'],
};
export function importPaths(file: string, source: string) {
  const paths: string[] = [];
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
  function visit(node: ts.Node) {
    if (
      (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
      node.moduleSpecifier &&
      ts.isStringLiteral(node.moduleSpecifier)
    )
      paths.push(node.moduleSpecifier.text);
    if (
      ts.isImportEqualsDeclaration(node) &&
      ts.isExternalModuleReference(node.moduleReference) &&
      node.moduleReference.expression &&
      ts.isStringLiteral(node.moduleReference.expression)
    )
      paths.push(node.moduleReference.expression.text);
    if (
      ts.isCallExpression(node) &&
      (node.expression.kind === ts.SyntaxKind.ImportKeyword ||
        (ts.isIdentifier(node.expression) && node.expression.text === 'require')) &&
      node.arguments[0] &&
      ts.isStringLiteral(node.arguments[0])
    )
      paths.push(node.arguments[0].text);
    if (
      ts.isImportTypeNode(node) &&
      ts.isLiteralTypeNode(node.argument) &&
      ts.isStringLiteral(node.argument.literal)
    )
      paths.push(node.argument.literal.text);
    ts.forEachChild(node, visit);
  }
  visit(tree);
  return paths;
}
export function violatesBoundary(layer: BoundaryLayer, file: string, specifier: string) {
  const target = specifier.startsWith('.')
    ? relative(process.cwd(), resolve(dirname(file), specifier)).replaceAll('\\', '/')
    : specifier;
  const internal = /^(?:packages\/|@studio\/)([^/]+)/.exec(target)?.[1];
  if (internal) return !allowedPackages[layer].includes(internal);
  if (target.startsWith('apps/')) return !target.startsWith('apps/web/') || layer !== 'web';
  if (specifier.startsWith('.')) return true;
  if (layer !== 'web') return specifier !== 'zod';
  return /^(?:pg(?:\/|$)|pg-boss(?:\/|$)|drizzle-orm(?:\/|$)|@supabase\/|fastify(?:\/|$)|node:)/.test(
    specifier,
  );
}
