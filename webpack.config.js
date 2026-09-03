const path = require('path');

module.exports = {
  entry: './web/main.js',
  output: {
    path: path.resolve(__dirname, 'web-dist'),
    filename: 'bundle.js',
    clean: true
  },
  resolve: {
    extensions: ['.js']
  },
  devtool: false,
  performance: { hints: false }
};
