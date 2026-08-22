% 使用 MATLAB 基础图形功能渲染八类科研绘图基准，不依赖额外工具箱。

scriptDir = fileparts(mfilename('fullpath'));
rootDir = fileparts(scriptDir);
dataDir = fullfile(rootDir, 'data');
stylePath = getenv('MMW_MATLAB_STYLE_CONTRACT');
if isempty(stylePath), stylePath = fullfile(rootDir, 'style_contract.json'); end
outputDir = getenv('MMW_MATLAB_OUTPUT_DIR');
if isempty(outputDir), outputDir = fullfile(rootDir, 'outputs', 'matlab'); end
reportDir = fullfile(rootDir, 'reports');
reportPath = getenv('MMW_MATLAB_REPORT_PATH');
if isempty(reportPath), reportPath = fullfile(reportDir, 'matlab_renderer.json'); end
if ~exist(outputDir, 'dir'), mkdir(outputDir); end
if ~exist(reportDir, 'dir'), mkdir(reportDir); end

set(groot, 'defaultAxesFontName', 'Microsoft YaHei');
set(groot, 'defaultTextFontName', 'Microsoft YaHei');
set(groot, 'defaultAxesFontSize', 11);
set(groot, 'defaultAxesLineWidth', 0.8);
rng(20260811, 'twister');
style = loadStyle(stylePath);
colors = style.colors;

ids = {'01_time_series', '02_scatter_fit', '03_distribution', ...
    '04_grouped_comparison', '05_heatmap', '06_sensitivity', ...
    '07_pareto', '08_gantt'};
renderers = {
    @() renderTimeSeries(dataDir, colors), ...
    @() renderScatterFit(dataDir, colors), ...
    @() renderDistribution(dataDir, colors), ...
    @() renderGroupedComparison(dataDir, colors), ...
    @() renderHeatmap(dataDir, colors), ...
    @() renderSensitivity(dataDir, colors), ...
    @() renderPareto(dataDir, colors), ...
    @() renderGantt(dataDir, colors) ...
};

generation = jsondecode(fileread(fullfile(reportDir, 'data_generation.json')));
dataHashes = containers.Map('KeyType', 'char', 'ValueType', 'char');
for i = 1:numel(generation.files)
    dataHashes(generation.files(i).file) = generation.files(i).sha256;
end

figures = repmat(struct('id', '', 'status', '', 'data_sha256', '', ...
    'png', '', 'pdf', '', 'reason', ''), 1, numel(ids));
failed = 0;
for i = 1:numel(ids)
    figures(i).id = ids{i};
    figures(i).data_sha256 = dataHashes(['data/' ids{i} '.csv']);
    try
        fig = renderers{i}();
        exportFigure(fig, outputDir, ids{i});
        close(fig);
        figures(i).status = 'rendered';
        figures(i).png = strrep(strrep(fullfile(outputDir, [ids{i} '.png']), [rootDir filesep], ''), '\', '/');
        figures(i).pdf = strrep(strrep(fullfile(outputDir, [ids{i} '.pdf']), [rootDir filesep], ''), '\', '/');
    catch err
        failed = failed + 1;
        figures(i).status = 'failed';
        figures(i).reason = sprintf('%s: %s', err.identifier, err.message);
        close all force;
    end
end

report = struct('schema_version', 1, 'backend', 'matlab', ...
    'palette_id', style.palette_id, 'figures', figures);
fid = fopen(reportPath, 'w', 'n', 'UTF-8');
fprintf(fid, '%s\n', jsonencode(report, 'PrettyPrint', true));
fclose(fid);
disp(jsonencode(report, 'PrettyPrint', true));
if failed > 0
    error('MMW:FigureBenchmark', '%d MATLAB figures failed; see matlab_renderer.json', failed);
end


function fig = newFigure()
fig = figure('Visible', 'off', 'Color', 'white', 'Position', [100 100 1600 1000]);
end


function styleAxes(ax, chartTitle, xLabel, yLabel, colors, gridAxis)
if nargin < 6, gridAxis = 'y'; end
title(ax, chartTitle, 'FontSize', 15, 'FontWeight', 'normal', 'Color', colors.text);
xlabel(ax, xLabel, 'FontSize', 12, 'Color', colors.text);
ylabel(ax, yLabel, 'FontSize', 12, 'Color', colors.text);
box(ax, 'off');
ax.TickDir = 'out';
ax.LineWidth = 0.8;
ax.XColor = colors.text;
ax.YColor = colors.text;
ax.GridColor = colors.grid;
ax.GridAlpha = 0.85;
ax.Layer = 'top';
switch gridAxis
    case 'x'
        ax.XGrid = 'on'; ax.YGrid = 'off';
    case 'both'
        ax.XGrid = 'on'; ax.YGrid = 'on';
    case 'none'
        ax.XGrid = 'off'; ax.YGrid = 'off';
    otherwise
        ax.XGrid = 'off'; ax.YGrid = 'on';
end
end


function exportFigure(fig, outputDir, id)
drawnow;
exportgraphics(fig, fullfile(outputDir, [id '.png']), ...
    'Resolution', 300, 'BackgroundColor', 'white');
exportgraphics(fig, fullfile(outputDir, [id '.pdf']), ...
    'ContentType', 'vector', 'BackgroundColor', 'white');
end


function fig = renderTimeSeries(dataDir, colors)
t = readtable(fullfile(dataDir, '01_time_series.csv'));
fig = newFigure(); ax = axes(fig); hold(ax, 'on');
x = t.day'; lower = t.lower_95'; upper = t.upper_95';
fill(ax, [x fliplr(x)], [lower fliplr(upper)], colors.primary, ...
    'FaceAlpha', 0.13, 'EdgeColor', 'none', 'DisplayName', '95% 预测区间');
plot(ax, t.day, t.observed, '-o', 'Color', colors.text, ...
    'LineWidth', 1.3, 'MarkerSize', 3, 'MarkerIndices', 1:3:height(t), 'DisplayName', '观测值');
plot(ax, t.day, t.forecast, '--', 'Color', colors.primary, ...
    'LineWidth', 2.0, 'DisplayName', '预测值');
styleAxes(ax, '需求预测与 95% 预测区间', '时间（天）', '需求量（单位/天）', colors);
legend(ax, 'Location', 'northwest', 'NumColumns', 3, 'Box', 'off');
xlim(ax, [min(t.day) max(t.day)]);
end


function fig = renderScatterFit(dataDir, colors)
t = readtable(fullfile(dataDir, '02_scatter_fit.csv'));
fig = newFigure(); ax = axes(fig); hold(ax, 'on');
x = t.x'; lower = t.lower_95'; upper = t.upper_95';
fill(ax, [x fliplr(x)], [lower fliplr(upper)], colors.primary, ...
    'FaceAlpha', 0.12, 'EdgeColor', 'none', 'DisplayName', '95% 均值置信带');
scatter(ax, t.x, t.observed, 30, 'MarkerFaceColor', colors.paper, ...
    'MarkerEdgeColor', colors.neutral_dark, 'DisplayName', '观测值');
plot(ax, t.x, t.fitted, '-', 'Color', colors.accent, ...
    'LineWidth', 2.0, 'DisplayName', '线性拟合');
styleAxes(ax, '变量关系与线性拟合', '解释变量 x（单位）', '响应变量 y（单位）', colors);
legend(ax, 'Location', 'northwest', 'Box', 'off');
end


function fig = renderDistribution(dataDir, colors)
t = readtable(fullfile(dataDir, '03_distribution.csv'), 'TextType', 'string');
groups = unique(t.group, 'stable');
distributionColors = [colors.primary; colors.accent; colors.teal];
fig = newFigure(); ax = axes(fig); hold(ax, 'on');
for i = 1:numel(groups)
    values = t.value(t.group == groups(i));
    y = linspace(min(values)-3, max(values)+3, 180);
    n = numel(values);
    bandwidth = 1.06 * std(values) * n^(-1/5);
    z = (y(:) - values(:)') / bandwidth;
    density = mean(exp(-0.5 * z.^2), 2) / (bandwidth * sqrt(2*pi));
    density = density / max(density) * 0.34;
    patch(ax, [i + zeros(size(y(:))); i + density], [y(:); flipud(y(:))], ...
        distributionColors(i,:), 'FaceAlpha', 0.22, 'EdgeColor', 'none');
    jitter = -0.28 + 0.22 * rand(size(values));
    scatter(ax, i + jitter, values, 22, distributionColors(i,:), 'filled', ...
        'MarkerFaceAlpha', 0.50, 'MarkerEdgeAlpha', 0.50);
    quartiles = quantile(values, [0.25 0.5 0.75]);
    plot(ax, [i i], [quartiles(1) quartiles(3)], 'Color', colors.text, 'LineWidth', 5);
    scatter(ax, i, quartiles(2), 42, colors.paper, 'filled', 'MarkerEdgeColor', colors.text);
end
xticks(ax, 1:numel(groups)); xticklabels(ax, groups);
xlim(ax, [0.45 numel(groups)+0.55]);
styleAxes(ax, '三种方案的结果分布', '方案', '指标值（分）', colors);
end


function fig = renderGroupedComparison(dataDir, colors)
t = readtable(fullfile(dataDir, '04_grouped_comparison.csv'), 'TextType', 'string');
fig = newFigure(); ax = axes(fig);
b = bar(ax, [t.baseline t.method_a t.method_b], 'grouped');
barColors = [colors.neutral; colors.primary; colors.accent];
for i = 1:numel(b)
    b(i).FaceColor = barColors(i,:);
    b(i).EdgeColor = colors.paper;
    b(i).LineWidth = 0.7;
end
xticks(ax, 1:height(t)); xticklabels(ax, t.scenario); ylim(ax, [0 90]);
styleAxes(ax, '不同场景下的方案得分', '场景', '综合得分（分）', colors);
legend(ax, {'基准', '方法 A', '方法 B'}, 'Location', 'northeast', 'NumColumns', 3, 'Box', 'off');
end


function fig = renderHeatmap(dataDir, colors)
t = readtable(fullfile(dataDir, '05_heatmap.csv'));
alphas = unique(t.alpha, 'stable'); betas = unique(t.beta, 'stable');
matrix = zeros(numel(betas), numel(alphas));
for r = 1:height(t)
    ix = find(alphas == t.alpha(r), 1); iy = find(betas == t.beta(r), 1);
    matrix(iy, ix) = t.delta_score(r);
end
fig = newFigure(); ax = axes(fig);
imagesc(ax, matrix); set(ax, 'YDir', 'normal');
blue = [linspace(colors.heat_low(1), colors.heat_mid(1), 128)' ...
    linspace(colors.heat_low(2), colors.heat_mid(2), 128)' ...
    linspace(colors.heat_low(3), colors.heat_mid(3), 128)'];
red = [linspace(colors.heat_mid(1), colors.heat_high(1), 129)' ...
    linspace(colors.heat_mid(2), colors.heat_high(2), 129)' ...
    linspace(colors.heat_mid(3), colors.heat_high(3), 129)'];
colormap(ax, [blue; red(2:end,:)]);
limit = max(abs(matrix), [], 'all'); clim(ax, [-limit limit]);
xticks(ax, 1:numel(alphas)); xticklabels(ax, compose('%.1f', alphas));
yticks(ax, 1:numel(betas)); yticklabels(ax, compose('%.1f', betas));
cb = colorbar(ax); cb.Label.String = '目标变化（%）';
styleAxes(ax, '参数组合相对基准的目标变化', '参数 α', '参数 β', colors, 'none');
end


function fig = renderSensitivity(dataDir, colors)
t = readtable(fullfile(dataDir, '06_sensitivity.csv'), 'TextType', 'string');
fig = newFigure(); ax = axes(fig); hold(ax, 'on');
b = barh(ax, [t.low_effect t.high_effect], 'grouped');
b(1).FaceColor = colors.primary; b(2).FaceColor = colors.accent;
b(1).EdgeColor = colors.paper; b(2).EdgeColor = colors.paper;
xline(ax, 0, '-', 'Color', colors.text, 'LineWidth', 0.8);
yticks(ax, 1:height(t)); yticklabels(ax, t.parameter);
styleAxes(ax, '参数敏感性 Tornado 图', '目标相对变化（%）', '参数', colors, 'x');
legend(ax, {'参数降低', '参数升高'}, 'Location', 'southeast', 'Box', 'off');
end


function fig = renderPareto(dataDir, colors)
t = readtable(fullfile(dataDir, '07_pareto.csv'));
front = sortrows(t(t.is_pareto == 1,:), 'cost'); dominated = t(t.is_pareto == 0,:);
fig = newFigure(); ax = axes(fig); hold(ax, 'on');
scatter(ax, dominated.cost, dominated.emissions, 32, colors.neutral, 'filled', ...
    'MarkerFaceAlpha', 0.58, 'DisplayName', '被支配候选');
plot(ax, front.cost, front.emissions, '-o', 'Color', colors.primary, ...
    'LineWidth', 2, 'MarkerFaceColor', colors.paper, ...
    'MarkerEdgeColor', colors.primary, 'DisplayName', '当前有限候选前沿');
styleAxes(ax, '成本与排放的有限候选权衡', '成本（万元）', '排放量（tCO_2）', colors, 'both');
legend(ax, 'Location', 'northeast', 'Box', 'off');
end


function fig = renderGantt(dataDir, colors)
t = readtable(fullfile(dataDir, '08_gantt.csv'), 'TextType', 'string', ...
    'VariableNamingRule', 'preserve');
resources = unique(t.resource, 'stable'); categories = unique(t.category, 'stable');
ganttColors = [colors.primary; colors.teal; colors.accent; colors.purple];
fig = newFigure(); ax = axes(fig); hold(ax, 'on');
for i = 1:height(t)
    y = find(resources == t.resource(i), 1);
    c = find(categories == t.category(i), 1);
    rectangle(ax, 'Position', [t.start(i), y-0.29, t.duration(i), 0.58], ...
        'FaceColor', ganttColors(c,:), 'EdgeColor', colors.paper, 'LineWidth', 0.8);
    text(ax, t.start(i) + t.duration(i)/2, y, t.task_id(i), ...
        'HorizontalAlignment', 'center', 'VerticalAlignment', 'middle', ...
        'Color', 'white', 'FontWeight', 'bold', 'FontSize', 9);
end
yticks(ax, 1:numel(resources)); yticklabels(ax, resources); set(ax, 'YDir', 'reverse');
xlim(ax, [0 max(t.("end"))+0.5]); ylim(ax, [0.4 numel(resources)+0.6]);
styleAxes(ax, '多资源任务调度甘特图', '时间（小时）', '资源', colors, 'x');
end


function style = loadStyle(path)
raw = jsondecode(fileread(path));
style = struct('palette_id', raw.palette_id, 'colors', struct());
names = fieldnames(raw.colors);
for i = 1:numel(names)
    name = names{i};
    style.colors.(name) = hexToRgb(raw.colors.(name));
end
end


function rgb = hexToRgb(value)
value = char(value);
rgb = [hex2dec(value(2:3)), hex2dec(value(4:5)), hex2dec(value(6:7))] / 255;
end
